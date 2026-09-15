"""CDC specimen collection manual: attachment discovery, viewer resolution, raw PDF retention.

Owner 2026-09-15: 「好 接下來做疾管署採檢手冊」. The official manual page lists the manual and its
revision table; each attachment link opens an HTML viewer that points at the uploaded PDF, whose
file name changes between uploads (SDD 10.3). The sync keeps both PDFs as one immutable raw
revision and writes a staged report; it never creates a candidate, curated build or current
descriptor. Reading the PDF layout is a later step (ADR 0003).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit

from .canonical import sha256_bytes, sha256_json
from .cdc_source import (
    _LAST_UPDATED_RE,
    _MAX_PAGE_BYTES,
    CDC_HOSTS,
    CDC_LICENSE_NAME,
    CDC_LICENSE_URL,
    CDC_PROVIDER,
    _fetch_evidence,
    _PageLinks,
)
from .fetch import FetchedArtifact, FetchError, fetch_https_bytes

CDC_MANUAL_SOURCE_ID = "cdc_specimen_manual"
CDC_MANUAL_DATASET_NAME = "傳染病檢體採檢手冊"
CDC_MANUAL_LANDING_URL = "https://www.cdc.gov.tw/Category/Page/WV_GRwCIYrWQsEVa8ctTWg"
PDF_MEDIA_TYPE = "application/pdf"
MAX_PDF_BYTES = 64 * 1024 * 1024
_MAX_VIEWER_BYTES = 512 * 1024
# role, attachment label, artifact id, stored file name
_DOCUMENTS = (
    (
        "manual",
        re.compile(r"^衛生福利部疾病管制署傳染病檢體採檢手冊-([0-9]{7})版\.pdf$"),
        "cdc-manual-pdf",
        "manual.pdf",
    ),
    (
        "revision_table",
        re.compile(r"^傳染病檢體採檢手冊修訂對照表-([0-9]{7})\.pdf$"),
        "cdc-manual-revision-pdf",
        "revision.pdf",
    ),
)
_UPLOADED_PDF_RE = re.compile(r"^/Uploads/[^/]+\.pdf$", re.IGNORECASE)


class CdcManualImportError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}{(': ' + detail) if detail else ''}")


class _ViewerLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.targets: list[str] = []
        self.downloads: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        target = values.get("href") if tag == "a" else values.get("src") or values.get("data")
        if tag not in {"a", "embed", "iframe", "object"} or not target:
            return
        self.targets.append(target)
        if tag == "a" and values.get("download") is not None:
            self.downloads.append((target, values["download"] or ""))


def _allowed_https(url: str) -> bool:
    parsed = urlsplit(url)
    host = parsed.hostname.rstrip(".").lower() if parsed.hostname else None
    return parsed.scheme.lower() == "https" and host in CDC_HOSTS


def discover_cdc_manual_resources(
    landing_payload: bytes, *, landing_url: str = CDC_MANUAL_LANDING_URL
) -> dict[str, Any]:
    """Find the manual and its revision table on the official page by their labels."""

    try:
        page = landing_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FetchError("DISCOVERY_PAGE_INVALID") from exc
    parser = _PageLinks()
    parser.feed(page)
    parser.close()
    documents = []
    versions = set()
    for role, label_re, _, _ in _DOCUMENTS:
        matches = set()
        for anchor in parser.anchors:
            label = " ".join(anchor["text"].split())
            match = label_re.fullmatch(label)
            viewer_url = urljoin(landing_url, anchor["href"])
            if match is not None and urlsplit(viewer_url).path.startswith("/File/Get/"):
                matches.add((label, match.group(1), viewer_url))
        if not matches:
            raise FetchError("DISCOVERY_RESOURCE_MISSING")
        if len(matches) > 1:
            raise FetchError("DISCOVERY_RESOURCE_AMBIGUOUS")
        label, version, viewer_url = matches.pop()
        if not _allowed_https(viewer_url):
            raise FetchError("FETCH_HOST_NOT_ALLOWED")
        versions.add(version)
        documents.append({"role": role, "attachment_label": label, "viewer_url": viewer_url})
    # The manual and its revision table must describe the same version.
    if len(versions) != 1:
        raise FetchError("DISCOVERY_VERSION_MISMATCH")
    updated = _LAST_UPDATED_RE.search(" ".join("".join(parser.text).split()))
    return {
        "provider": CDC_PROVIDER,
        "dataset_name": CDC_MANUAL_DATASET_NAME,
        "landing_url": landing_url,
        "landing_sha256": sha256_bytes(landing_payload),
        "landing_last_updated_raw": updated.group(1) if updated else None,
        "manual_version_raw": versions.pop(),
        "documents": documents,
        "license_name": CDC_LICENSE_NAME,
        "license_url": CDC_LICENSE_URL,
    }


def resolve_cdc_viewer_pdf(viewer_payload: bytes, *, viewer_url: str, attachment_label: str) -> str:
    """Return the one uploaded PDF the viewer page shows for this attachment."""

    try:
        page = viewer_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FetchError("DISCOVERY_PAGE_INVALID") from exc
    parser = _ViewerLinks()
    parser.feed(page)
    parser.close()
    candidates = set()
    for target in parser.targets:
        url = urldefrag(urljoin(viewer_url, target)).url
        if _UPLOADED_PDF_RE.fullmatch(urlsplit(url).path):
            candidates.add(url)
    if not candidates:
        raise FetchError("DISCOVERY_VIEWER_PDF_MISSING")
    if len(candidates) > 1:
        raise FetchError("DISCOVERY_VIEWER_PDF_AMBIGUOUS")
    pdf_url = candidates.pop()
    if not _allowed_https(pdf_url):
        raise FetchError("FETCH_HOST_NOT_ALLOWED")
    for target, label in parser.downloads:
        if urldefrag(urljoin(viewer_url, target)).url == pdf_url and label != attachment_label:
            raise FetchError("DISCOVERY_ATTACHMENT_MISMATCH")
    return pdf_url


def cdc_manual_raw_revision_id(
    *, discovery: dict[str, Any], artifacts: dict[str, FetchedArtifact]
) -> str:
    """RawRevisionFingerprintV1 for the two PDFs; page hashes, viewer pages and upload names stay out."""

    return sha256_json(
        {
            "fingerprint_schema": "raw-revision-v1",
            "source_id": CDC_MANUAL_SOURCE_ID,
            "discovery": {
                "landing_url": discovery["landing_url"],
                "manual_version_raw": discovery["manual_version_raw"],
                "license_name": discovery["license_name"],
                "license_url": discovery["license_url"],
                "documents": [
                    {"role": document["role"], "attachment_label": document["attachment_label"]}
                    for document in discovery["documents"]
                ],
            },
            "artifacts": [
                {
                    "artifact_id": artifact_id,
                    "role": role,
                    "media_type_verified": PDF_MEDIA_TYPE,
                    "bytes": len(artifacts[role].payload),
                    "sha256": artifacts[role].sha256,
                }
                for role, _, artifact_id, _ in _DOCUMENTS
            ],
        }
    )


def _write_raw_revision(
    data_root: Path,
    raw_revision_id: str,
    artifacts: dict[str, FetchedArtifact],
    discovery: dict[str, Any],
) -> tuple[dict[str, str], str]:
    from .sync import SyncError, _write_immutable_json, _write_new_file

    revision_dir = PurePosixPath("raw", CDC_MANUAL_SOURCE_ID, raw_revision_id)
    paths: dict[str, str] = {}
    records = []
    for role, _, artifact_id, file_name in _DOCUMENTS:
        artifact = artifacts[role]
        if artifact.sha256 != sha256_bytes(artifact.payload):
            raise SyncError("RAW_ARTIFACT_HASH_MISMATCH", "fetch")
        relative = str(revision_dir / "artifacts" / file_name)
        path = data_root / PurePosixPath(relative)
        if path.exists():
            if path.read_bytes() != artifact.payload:
                raise SyncError("IMMUTABLE_RAW_CONFLICT", "fetch")
        else:
            _write_new_file(path, artifact.payload)
        paths[role] = relative
        records.append(
            {
                "artifact_id": artifact_id,
                "role": role,
                "data_root_relative_path": relative,
                "media_type_verified": PDF_MEDIA_TYPE,
                **_fetch_evidence(artifact),
            }
        )
    fetch_relative = str(revision_dir / "fetch.json")
    fetch_path = data_root / PurePosixPath(fetch_relative)
    # A later fetch of identical PDFs keeps the first fetch record untouched.
    if not fetch_path.exists():
        _write_immutable_json(
            fetch_path,
            {
                "fetch_record_schema_version": 1,
                "source_id": CDC_MANUAL_SOURCE_ID,
                "raw_revision_id": raw_revision_id,
                "discovery": discovery,
                "artifacts": records,
            },
        )
    return paths, fetch_relative


def _validate_pdf(payload: bytes) -> None:
    if not payload.startswith(b"%PDF-"):
        raise CdcManualImportError("PDF_NOT_PDF")
    if b"%%EOF" not in payload[-1024:]:
        raise CdcManualImportError("PDF_TRUNCATED")


def run_cdc_manual_upstream_sync(
    data_root: Path,
    *,
    landing_url: str = CDC_MANUAL_LANDING_URL,
    timeout_seconds: float = 60.0,
    max_redirects: int = 3,
    opener=None,
    clock=None,
) -> dict[str, Any]:
    """Discover, fetch and check both manual PDFs; keep raw bytes; never publish."""

    from .sync import SyncError, _attempt_id, _utc_now, _write_immutable_json

    data_root = Path(data_root)
    started_at = _utc_now(clock)
    attempt_id = _attempt_id(CDC_MANUAL_SOURCE_ID, None, started_at)
    report_relative = str(
        PurePosixPath("staged", CDC_MANUAL_SOURCE_ID, attempt_id, "validation.json")
    )
    stage = "discover"
    error_code = None
    discovery = None
    artifacts: dict[str, FetchedArtifact] = {}
    raw_revision_id = None
    artifact_paths = None
    fetch_relative = None

    def fetch(url: str, max_bytes: int, content_types: set[str]) -> FetchedArtifact:
        return fetch_https_bytes(
            url,
            allowed_hosts=CDC_HOSTS,
            max_bytes=max_bytes,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            allowed_content_types=content_types,
            opener=opener,
            clock=clock,
        )

    try:
        landing = fetch(landing_url, _MAX_PAGE_BYTES, {"text/html"})
        discovery = {
            **discover_cdc_manual_resources(landing.payload, landing_url=landing_url),
            "landing_final_url": landing.final_url,
            "landing_fetched_at": landing.fetched_at,
        }
        stage = "fetch"
        for document in discovery["documents"]:
            viewer = fetch(document["viewer_url"], _MAX_VIEWER_BYTES, {"text/html"})
            pdf_url = resolve_cdc_viewer_pdf(
                viewer.payload,
                viewer_url=viewer.final_url,
                attachment_label=document["attachment_label"],
            )
            document.update(
                viewer_final_url=viewer.final_url,
                viewer_sha256=viewer.sha256,
                viewer_fetched_at=viewer.fetched_at,
                pdf_url=pdf_url,
            )
            artifacts[document["role"]] = fetch(
                pdf_url, MAX_PDF_BYTES, {PDF_MEDIA_TYPE, "application/octet-stream"}
            )
        # Both PDFs arrived; only now does the raw revision exist.
        raw_revision_id = cdc_manual_raw_revision_id(discovery=discovery, artifacts=artifacts)
        artifact_paths, fetch_relative = _write_raw_revision(
            data_root, raw_revision_id, artifacts, discovery
        )
        stage = "validate"
        for role, _, _, _ in _DOCUMENTS:
            _validate_pdf(artifacts[role].payload)
    except (FetchError, SyncError, CdcManualImportError) as exc:
        error_code = exc.code
    completed_at = _utc_now(clock)
    report = {
        "sync_report_schema_version": 1,
        "attempt_id": attempt_id,
        "source_id": CDC_MANUAL_SOURCE_ID,
        "input_kind": "upstream",
        "stage": stage,
        "status": "failed" if error_code else "passed",
        "error_code": error_code,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "raw_revision_id": raw_revision_id if artifact_paths else None,
        "raw_artifact_data_root_relative_paths": artifact_paths,
        "raw_fetch_record_data_root_relative_path": fetch_relative,
        "discovery": discovery,
        "fetch": {role: _fetch_evidence(artifact) for role, artifact in artifacts.items()} or None,
        "candidate_status": "none",
        "blocking_errors": [error_code] if error_code else [],
        "report_data_root_relative_path": report_relative,
    }
    _write_immutable_json(data_root / PurePosixPath(report_relative), report)
    return report
