"""CDC specimen collection manual: attachment discovery, viewer resolution, raw PDF retention.

Owner 2026-09-15: 「好 接下來做疾管署採檢手冊」. The official manual page lists the manual and its
revision table; each attachment link opens an HTML viewer that points at the uploaded PDF, whose
file name changes between uploads (SDD 10.3). The sync keeps both PDFs as one immutable raw
revision and writes a staged report; it never creates a candidate, curated build or current
descriptor. Reading the PDF layout is a later step (ADR 0003).
"""

from __future__ import annotations

import json
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


_DIFF_LIST_LIMIT = 50


def _read_cdc_manual_serving(data_root: Path) -> dict[str, Any] | None:
    from .sync import SyncError

    descriptor_path = data_root / "manifests" / "current" / f"{CDC_MANUAL_SOURCE_ID}.json"
    if not descriptor_path.is_file():
        return None
    try:
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        serving_id = descriptor["serving_curated_build_id"]
        if serving_id is None:
            return None
        manifest_path = data_root / PurePosixPath(descriptor["manifest_data_root_relative_path"])
        manifest_bytes = manifest_path.read_bytes()
        if sha256_bytes(manifest_bytes) != descriptor["manifest_sha256"]:
            raise SyncError("CURRENT_POINTER_INTEGRITY", "check")
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        return {
            "descriptor": descriptor,
            "serving_id": serving_id,
            "raw_revision_id": manifest["raw_revision_id"],
            "artifact_sha256": manifest["artifacts"][0]["sha256"],
            "manual_version": manifest["official_version"]["label"],
            "transform": manifest["transform"],
            "db_path": data_root
            / PurePosixPath(manifest["publication"]["curated_build_relative_path"]),
        }
    except (KeyError, IndexError, OSError, TypeError, UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, SyncError):
            raise
        raise SyncError("CURRENT_POINTER_INTEGRITY", "check") from exc


def _served_rows(db_path: Path, table: str = "cdc_specimen_requirement") -> list[dict[str, Any]]:
    from .importers.cdc_manual_layout import CDC_MANUAL_TABLE_NAMES
    from .tfda_store import connect_readonly

    if table not in CDC_MANUAL_TABLE_NAMES:
        raise ValueError(table)
    connection = connect_readonly(db_path)
    try:
        return [
            dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY row_number")
        ]
    finally:
        connection.close()


def _parsed_rows(payload: bytes) -> list[dict[str, Any]]:
    """Rows of a manual PDF shaped like the curated table (raw and display text, row hash)."""

    from .importers import cdc_manual
    from .importers.cdc_manual_layout import parse_cdc_specimen_layout

    parsed = parse_cdc_specimen_layout(cdc_manual.extract_cdc_manual_layout(payload))
    return [
        cdc_manual.curated_specimen_row(row, number, parsed.summary)
        for number, row in enumerate(parsed.rows, start=1)
    ]


def _row_label(row: dict[str, Any]) -> str:
    parts = (
        row["table_section"],
        row["disease_display"],
        row["specimen_display"],
        row["collection_time_display"],
    )
    return "｜".join(" ".join(str(part or "").split()) for part in parts)


def _manual_diff(serving: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> dict[str, Any]:
    def grouped(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for row in rows:
            groups.setdefault(_row_label(row), []).append(row["source_row_sha256"])
        return groups

    before, after = grouped(serving), grouped(candidate)
    return {
        "row_counts": {"serving": len(serving), "candidate": len(candidate)},
        "disease_counts": {
            "serving": len({row["disease_display"] for row in serving}),
            "candidate": len({row["disease_display"] for row in candidate}),
        },
        "changed_rows": sorted(
            label
            for label in before.keys() & after.keys()
            if sorted(before[label]) != sorted(after[label])
        ),
        "added_rows": sorted(after.keys() - before.keys()),
        "removed_rows": sorted(before.keys() - after.keys()),
    }


def _manual_diff_markdown(
    diff: dict[str, Any],
    *,
    checked_at: str,
    serving_id: str,
    serving_version: str,
    candidate_version: str,
) -> str:
    rows, diseases = diff["row_counts"], diff["disease_counts"]
    lines = [
        "# 疾管署傳染病檢體採檢手冊：上游有新版",
        "",
        f"- 檢查時間（UTC）：{checked_at}",
        f"- 手冊版本：服務中 {serving_version} → 新版 {candidate_version}",
        f"- 比對的服務中版本：`{serving_id}`",
        f"- 第 2 章資料列：服務中 {rows['serving']:,} 列 → 新版 {rows['candidate']:,} 列",
        f"- 疾病：服務中 {diseases['serving']:,} 種 → 新版 {diseases['candidate']:,} 種",
        f"- 內容有改的列：{len(diff['changed_rows']):,} 列；新版才有的列："
        f"{len(diff['added_rows']):,} 列；新版沒有的列：{len(diff['removed_rows']):,} 列",
        "",
    ]
    for title, items in (
        ("內容有改的列", diff["changed_rows"]),
        ("新版才有的列", diff["added_rows"]),
        ("新版沒有的列", diff["removed_rows"]),
    ):
        lines.extend([f"## {title}（{len(items):,} 列；節｜疾病｜檢體｜採檢時間）", ""])
        lines.extend(f"- {item}" for item in items[:_DIFF_LIST_LIMIT])
        if not items:
            lines.append("（無）")
        elif len(items) > _DIFF_LIST_LIMIT:
            lines.append(f"- …另外 {len(items) - _DIFF_LIST_LIMIT:,} 列，完整清單見 diff.json")
        lines.append("")
    return "\n".join(lines)


def run_cdc_manual_upstream_check(
    data_root: Path,
    *,
    actor: str,
    landing_url: str = CDC_MANUAL_LANDING_URL,
    opener=None,
    clock=None,
) -> dict[str, Any]:
    """Check the official manual page once and record the result without switching the manual.

    The same raw revision as the serving build records a successful check. A different one keeps
    serving the current build, marks a review-pending candidate and writes a row diff. A failed
    fetch or validation keeps serving the current build and marks it stale.
    """

    from .importers.cdc_manual_layout import CdcManualLayoutError
    from .publish import publish_operational_check
    from .sync import _write_immutable_json, _write_new_file

    data_root = Path(data_root)
    serving = _read_cdc_manual_serving(data_root)
    report = run_cdc_manual_upstream_sync(
        data_root, landing_url=landing_url, opener=opener, clock=clock
    )
    discovery = report["discovery"] or {}
    summary: dict[str, Any] = {
        "result": None,
        "sync_report_data_root_relative_path": report["report_data_root_relative_path"],
        "diff_data_root_relative_path": None,
        "diff_summary_data_root_relative_path": None,
        "diff_error_code": None,
        "candidate_raw_revision_id": None,
        "manual_version": discovery.get("manual_version_raw"),
        "failed_stage": None if report["status"] == "passed" else report["stage"],
        "error_code": report["error_code"],
        "check_id": None,
        "generation": None,
        "stale": None,
        "stale_reason_codes": None,
    }
    if serving is None:
        summary["result"] = "no_serving_snapshot"
        return summary

    descriptor = serving["descriptor"]
    raw_revision_id = report["raw_revision_id"]
    saved_sha256 = report["fetch"]["manual"]["sha256"] if raw_revision_id else None
    seen_version = discovery["manual_version_raw"] if raw_revision_id else None
    candidate_id = None
    candidate_status = "none"
    if report["status"] != "passed":
        result = "failed"
        check_result = "failed"
        reasons = ["upstream_verification_failed"]
        if raw_revision_id is not None and raw_revision_id != serving["raw_revision_id"]:
            candidate_status = "rejected"
            candidate_id = raw_revision_id
            reasons.append("newer_candidate_rejected")
        seen_sha256 = saved_sha256 or descriptor["latest_seen_artifact_sha256"]
        seen_version = seen_version or descriptor["latest_seen_version"]
    elif raw_revision_id == serving["raw_revision_id"]:
        result = "unchanged"
        check_result = "success"
        reasons = []
        seen_sha256 = saved_sha256
    else:
        result = "changed"
        check_result = "success"
        candidate_status = "review_pending"
        candidate_id = raw_revision_id
        reasons = ["newer_candidate_pending_review"]
        seen_sha256 = saved_sha256
        try:
            candidate_payload = (
                data_root / PurePosixPath(report["raw_artifact_data_root_relative_paths"]["manual"])
            ).read_bytes()
            diff = _manual_diff(_served_rows(serving["db_path"]), _parsed_rows(candidate_payload))
        except (CdcManualLayoutError, CdcManualImportError) as exc:
            # The auto update reads the new manual again and reports the same code.
            summary["diff_error_code"] = exc.code
        else:
            attempt_dir = PurePosixPath(report["report_data_root_relative_path"]).parent
            diff_relative = str(attempt_dir / "diff.json")
            summary_relative = str(attempt_dir / "diff-summary.md")
            _write_immutable_json(
                data_root / PurePosixPath(diff_relative),
                {
                    "diff_schema_version": 1,
                    "source_id": CDC_MANUAL_SOURCE_ID,
                    "checked_at": report["completed_at"],
                    "serving_snapshot_id": serving["serving_id"],
                    "serving_manual_version": serving["manual_version"],
                    "serving_raw_revision_id": serving["raw_revision_id"],
                    "candidate_raw_revision_id": candidate_id,
                    "candidate_manual_version": seen_version,
                    **diff,
                },
            )
            _write_new_file(
                data_root / PurePosixPath(summary_relative),
                _manual_diff_markdown(
                    diff,
                    checked_at=report["completed_at"],
                    serving_id=serving["serving_id"],
                    serving_version=serving["manual_version"],
                    candidate_version=seen_version,
                ).encode("utf-8"),
            )
            summary["diff_data_root_relative_path"] = diff_relative
            summary["diff_summary_data_root_relative_path"] = summary_relative

    check = {
        "check_schema_version": 1,
        "check_id": f"{CDC_MANUAL_SOURCE_ID}-check-{report['attempt_id'].lower()}",
        "source_id": CDC_MANUAL_SOURCE_ID,
        "generation": descriptor["generation"] + 1,
        "serving_snapshot_id": serving["serving_id"],
        "serving_curated_build_id": serving["serving_id"],
        "checked_at": report["completed_at"],
        "latest_seen_version": seen_version,
        "latest_seen_artifact_sha256": seen_sha256,
        "latest_candidate_id": candidate_id,
        "latest_candidate_status": candidate_status,
        "check_result": check_result,
        "failed_stage": summary["failed_stage"],
        "error_code": summary["error_code"],
        "stale": bool(reasons),
        "stale_reason_codes": reasons,
        "freshness_policy_version": descriptor["freshness_policy_version"],
        "content_age_status": descriptor["content_age_status"],
        "content_age_evidence": descriptor["content_age_evidence"],
    }
    event = publish_operational_check(
        data_root,
        CDC_MANUAL_SOURCE_ID,
        check,
        expected_generation=descriptor["generation"],
        actor=actor,
    )
    summary.update(
        {
            "result": result,
            "candidate_raw_revision_id": candidate_id,
            "check_id": check["check_id"],
            "generation": event["generation"],
            "stale": check["stale"],
            "stale_reason_codes": reasons,
        }
    )
    return summary
