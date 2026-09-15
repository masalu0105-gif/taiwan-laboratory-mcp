"""CDC recognized laboratory roster: attachment discovery, raw ODS retention, validation.

Owner 2026-09-15 started the CDC source (「A 開始做疾管署」) and delegated its reviews to AI
(OD-04). The official page lists shared site links next to the roster attachment, so the roster
is picked by its label and the download must carry the same file name. This path keeps the
fetched ODS as an immutable raw revision and writes a staged validation report; it never
creates a candidate, curated build or current descriptor.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from .canonical import sha256_bytes, sha256_json
from .fetch import FetchedArtifact, FetchError, fetch_https_bytes
from .importers.cdc_labs import (
    CDC_LABS_DATASET_NAME,
    CDC_LABS_PRIMARY_ARTIFACT_ID,
    CDC_LABS_PROVIDER,
)
from .importers.cdc_ods import (
    CDC_LABS_PARSER_VERSION,
    CDC_LABS_SCHEMA_VERSION,
    CDC_LABS_SOURCE_ID,
    DEFAULT_ODS_LIMITS,
    ODS_MIMETYPE,
    CdcOdsImportError,
    parse_cdc_labs_ods,
)

CDC_PROVIDER = CDC_LABS_PROVIDER
CDC_HOSTS = frozenset({"www.cdc.gov.tw"})
CDC_LICENSE_NAME = "衛生福利部疾病管制署政府網站資料開放宣告"
CDC_LICENSE_URL = "https://www.cdc.gov.tw/Category/FPage/TxkBIR9agw_IBRRmvn9TcQ"
CDC_LABS_LANDING_URL = "https://www.cdc.gov.tw/Category/Page/02d-tR1nzB8QuflX-NmM_w"
ODS_MEDIA_TYPE = ODS_MIMETYPE.decode("ascii")
_ROSTER_LABEL_RE = re.compile(r"^傳染病認可檢驗機構名冊([0-9]{7})\.ods$")
_LAST_UPDATED_RE = re.compile(r"最後更新日期\s*([0-9]{4}/[0-9]{1,2}/[0-9]{1,2})")
_FILENAME_STAR_RE = re.compile(r"filename\*\s*=\s*UTF-8''([^;]+)", re.IGNORECASE)
_FILENAME_RE = re.compile(r'filename\s*=\s*"?([^";]+)"?', re.IGNORECASE)
_MAX_PAGE_BYTES = 2 * 1024 * 1024


class _PageLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict[str, str]] = []
        self.text: list[str] = []
        self._anchor: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            values = dict(attrs)
            self._anchor = {"href": values.get("href") or "", "text": ""}

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor is not None:
            self.anchors.append(self._anchor)
            self._anchor = None

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._anchor is not None:
            self._anchor["text"] += data


def discover_cdc_labs_resource(
    landing_payload: bytes, *, landing_url: str = CDC_LABS_LANDING_URL
) -> dict[str, Any]:
    """Find the one roster attachment on the official page by its label."""

    try:
        page = landing_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FetchError("DISCOVERY_PAGE_INVALID") from exc
    parser = _PageLinks()
    parser.feed(page)
    parser.close()
    matches = set()
    for anchor in parser.anchors:
        label = " ".join(anchor["text"].split())
        match = _ROSTER_LABEL_RE.fullmatch(label)
        resource_url = urljoin(landing_url, anchor["href"])
        if match is not None and urlsplit(resource_url).path.startswith("/File/Get/"):
            matches.add((label, match.group(1), resource_url))
    if not matches:
        raise FetchError("DISCOVERY_RESOURCE_MISSING")
    if len(matches) > 1:
        raise FetchError("DISCOVERY_RESOURCE_AMBIGUOUS")
    label, version, resource_url = matches.pop()
    parsed = urlsplit(resource_url)
    host = parsed.hostname.rstrip(".").lower() if parsed.hostname else None
    if parsed.scheme.lower() != "https" or host not in CDC_HOSTS:
        raise FetchError("FETCH_HOST_NOT_ALLOWED")
    updated = _LAST_UPDATED_RE.search(" ".join("".join(parser.text).split()))
    return {
        "provider": CDC_PROVIDER,
        "dataset_name": CDC_LABS_DATASET_NAME,
        "landing_url": landing_url,
        "landing_sha256": sha256_bytes(landing_payload),
        "landing_last_updated_raw": updated.group(1) if updated else None,
        "attachment_label": label,
        "roster_version_raw": version,
        "resource_url": resource_url,
        "license_name": CDC_LICENSE_NAME,
        "license_url": CDC_LICENSE_URL,
    }


def cdc_labs_raw_revision_id(
    *, payload_sha256: str, payload_size: int, discovery: dict[str, Any]
) -> str:
    """RawRevisionFingerprintV1 for one roster ODS; the volatile page hash and token stay out."""

    return sha256_json(
        {
            "fingerprint_schema": "raw-revision-v1",
            "source_id": CDC_LABS_SOURCE_ID,
            "discovery": {
                key: discovery.get(key)
                for key in (
                    "landing_url",
                    "attachment_label",
                    "roster_version_raw",
                    "license_name",
                    "license_url",
                )
            },
            "artifacts": [
                {
                    "artifact_id": CDC_LABS_PRIMARY_ARTIFACT_ID,
                    "role": "primary",
                    "media_type_verified": ODS_MEDIA_TYPE,
                    "bytes": payload_size,
                    "sha256": payload_sha256,
                }
            ],
        }
    )


def _disposition_filename(headers: dict[str, str]) -> str | None:
    value = headers.get("content-disposition")
    if not value:
        return None
    match = _FILENAME_STAR_RE.search(value)
    if match is not None:
        return unquote(match.group(1).strip())
    match = _FILENAME_RE.search(value)
    return match.group(1).strip() if match is not None else None


def _fetch_evidence(artifact: FetchedArtifact) -> dict[str, Any]:
    return {
        "requested_url": artifact.requested_url,
        "final_url": artifact.final_url,
        "status_code": artifact.status_code,
        "headers": artifact.headers,
        "redirect_trace": list(artifact.redirect_trace),
        "bytes": len(artifact.payload),
        "sha256": artifact.sha256,
        "fetched_at": artifact.fetched_at,
    }


def _write_raw_revision(
    data_root: Path, raw_revision_id: str, artifact: FetchedArtifact, discovery: dict[str, Any]
) -> tuple[str, str]:
    from .sync import SyncError, _write_immutable_json, _write_new_file

    if artifact.sha256 != sha256_bytes(artifact.payload):
        raise SyncError("RAW_ARTIFACT_HASH_MISMATCH", "fetch")
    revision_dir = PurePosixPath("raw", CDC_LABS_SOURCE_ID, raw_revision_id)
    artifact_relative = str(revision_dir / "artifacts" / "source.ods")
    fetch_relative = str(revision_dir / "fetch.json")
    artifact_path = data_root / PurePosixPath(artifact_relative)
    if artifact_path.exists():
        if artifact_path.read_bytes() != artifact.payload:
            raise SyncError("IMMUTABLE_RAW_CONFLICT", "fetch")
    else:
        _write_new_file(artifact_path, artifact.payload)
    fetch_path = data_root / PurePosixPath(fetch_relative)
    # A later fetch of identical bytes keeps the first fetch record untouched.
    if not fetch_path.exists():
        _write_immutable_json(
            fetch_path,
            {
                "fetch_record_schema_version": 1,
                "source_id": CDC_LABS_SOURCE_ID,
                "raw_revision_id": raw_revision_id,
                "discovery": discovery,
                "artifact": {
                    "artifact_id": CDC_LABS_PRIMARY_ARTIFACT_ID,
                    "role": "primary",
                    "data_root_relative_path": artifact_relative,
                    "media_type_verified": ODS_MEDIA_TYPE,
                    **_fetch_evidence(artifact),
                },
            },
        )
    return artifact_relative, fetch_relative


def run_cdc_labs_upstream_sync(
    data_root: Path,
    *,
    landing_url: str = CDC_LABS_LANDING_URL,
    timeout_seconds: float = 60.0,
    max_redirects: int = 3,
    opener=None,
    clock=None,
) -> dict[str, Any]:
    """Discover, fetch and validate the roster ODS; keep raw bytes; never publish."""

    from .sync import SyncError, _attempt_id, _utc_now, _write_immutable_json

    data_root = Path(data_root)
    started_at = _utc_now(clock)
    attempt_id = _attempt_id(CDC_LABS_SOURCE_ID, None, started_at)
    report_relative = str(
        PurePosixPath("staged", CDC_LABS_SOURCE_ID, attempt_id, "validation.json")
    )
    stage = "discover"
    error_code = None
    discovery = None
    artifact = None
    raw_revision_id = None
    artifact_relative = None
    fetch_relative = None
    summary = None
    try:
        landing = fetch_https_bytes(
            landing_url,
            allowed_hosts=CDC_HOSTS,
            max_bytes=_MAX_PAGE_BYTES,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            allowed_content_types={"text/html"},
            opener=opener,
            clock=clock,
        )
        discovery = {
            **discover_cdc_labs_resource(landing.payload, landing_url=landing_url),
            "landing_final_url": landing.final_url,
            "landing_fetched_at": landing.fetched_at,
        }
        stage = "fetch"
        artifact = fetch_https_bytes(
            discovery["resource_url"],
            allowed_hosts=CDC_HOSTS,
            max_bytes=DEFAULT_ODS_LIMITS.max_archive_bytes,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            allowed_content_types={"application/octet-stream", ODS_MEDIA_TYPE},
            opener=opener,
            clock=clock,
        )
        filename = _disposition_filename(artifact.headers)
        if filename is not None and filename != discovery["attachment_label"]:
            raise FetchError("DISCOVERY_ATTACHMENT_MISMATCH")
        raw_revision_id = cdc_labs_raw_revision_id(
            payload_sha256=artifact.sha256, payload_size=len(artifact.payload), discovery=discovery
        )
        artifact_relative, fetch_relative = _write_raw_revision(
            data_root, raw_revision_id, artifact, discovery
        )
        stage = "parse"
        parsed = parse_cdc_labs_ods(artifact.payload)
        summary = parsed.summary
        stage = "validate"
        # The attachment label and the roster sheet name carry the same ROC date version.
        if parsed.sheet_name != f"{discovery['roster_version_raw']}名冊":
            raise CdcOdsImportError("ODS_VERSION_MISMATCH", parsed.sheet_name)
    except (FetchError, SyncError, CdcOdsImportError) as exc:
        error_code = exc.code
    except MemoryError:
        # Keep the stage and any already-saved raw ODS; report instead of crashing.
        error_code = "RESOURCE_EXHAUSTED"
    completed_at = _utc_now(clock)
    report = {
        "sync_report_schema_version": 1,
        "attempt_id": attempt_id,
        "source_id": CDC_LABS_SOURCE_ID,
        "input_kind": "upstream",
        "stage": stage,
        "status": "failed" if error_code else "passed",
        "error_code": error_code,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "raw_revision_id": raw_revision_id if artifact_relative else None,
        "raw_artifact_data_root_relative_path": artifact_relative,
        "raw_fetch_record_data_root_relative_path": fetch_relative,
        "discovery": discovery,
        "fetch": _fetch_evidence(artifact) if artifact is not None else None,
        "candidate_status": "none",
        "transform": {
            "parser_version": CDC_LABS_PARSER_VERSION,
            "schema_version": CDC_LABS_SCHEMA_VERSION,
        },
        "blocking_errors": [error_code] if error_code else [],
        "summary": summary,
        "report_data_root_relative_path": report_relative,
    }
    _write_immutable_json(data_root / PurePosixPath(report_relative), report)
    return report
