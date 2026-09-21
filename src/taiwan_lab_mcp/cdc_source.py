"""CDC recognized laboratory roster: attachment discovery, raw ODS retention, validation.

Owner 2026-09-15 started the CDC source (「A 開始做疾管署」) and delegated its reviews to AI
(OD-04). The official page lists shared site links next to the roster attachment, so the roster
is picked by its label and the download must carry the same file name. The sync keeps the
fetched ODS as an immutable raw revision and writes a staged validation report; it never
creates a candidate, curated build or current descriptor. The daily check records its result
on the current descriptor without switching the served roster.
"""

from __future__ import annotations

import json
import re
from collections import Counter
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
    CDC_LABS_COLUMNS,
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
# CDC spaced the label version on 2026-09-18 (名冊 1150918.ods); files up to 1150916 had none.
_ROSTER_LABEL_RE = re.compile(r"^傳染病認可檢驗機構名冊\s*([0-9]{7})\.ods$")
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


_DIFF_LIST_LIMIT = 50
_DIFF_CHANGE_LIMIT = 5
# Disease code, purpose and method tell the rows of one certificate apart.
_ROW_KEY_COLUMNS = (4, 6, 7)


def _short(value: str, limit: int = 80) -> str:
    text = " ".join((value or "").split())
    if not text:
        return "（空白）"
    return text if len(text) <= limit else text[:limit] + "…"


def _read_cdc_labs_serving(data_root: Path) -> dict[str, Any] | None:
    from .sync import SyncError

    descriptor_path = data_root / "manifests" / "current" / f"{CDC_LABS_SOURCE_ID}.json"
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
        artifact = manifest["artifacts"][0]
        return {
            "descriptor": descriptor,
            "serving_id": serving_id,
            "artifact_sha256": artifact["sha256"],
            "artifact_relative": artifact["data_root_relative_path"],
            "roster_version": manifest["official_version"]["label"],
            "transform": manifest["transform"],
        }
    except (KeyError, IndexError, OSError, TypeError, UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, SyncError):
            raise
        raise SyncError("CURRENT_POINTER_INTEGRITY", "check") from exc


def _read_hashed_raw(data_root: Path, relative: str, expected_sha256: str) -> bytes:
    from .sync import SyncError

    payload = (data_root / PurePosixPath(relative)).read_bytes()
    if sha256_bytes(payload) != expected_sha256:
        raise SyncError("RAW_ARTIFACT_READBACK_MISMATCH", "check")
    return payload


def _rows_by_certificate(payload: bytes) -> dict[str, list[tuple[str, ...]]]:
    rows: dict[str, list[tuple[str, ...]]] = {}
    for row in parse_cdc_labs_ods(payload).rows:
        rows.setdefault(row.values[0], []).append(row.values)
    return rows


def _row_label(values: tuple[str, ...]) -> str:
    return f"{values[5]}（{values[4]}）{values[6]}／{values[7]}"


def _certificate_changes(
    before_rows: list[tuple[str, ...]], after_rows: list[tuple[str, ...]]
) -> list[dict[str, Any]]:
    def grouped(rows: list[tuple[str, ...]]) -> dict[tuple[str, ...], list[tuple[str, ...]]]:
        groups: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
        for values in rows:
            groups.setdefault(tuple(values[i] for i in _ROW_KEY_COLUMNS), []).append(values)
        return groups

    before, after = grouped(before_rows), grouped(after_rows)
    changes: list[dict[str, Any]] = []
    for key in sorted(before.keys() | after.keys()):
        old_rows, new_rows = before.get(key, []), after.get(key, [])
        for old, new in zip(old_rows, new_rows):
            fields = [
                {"column": column, "before": old_value, "after": new_value}
                for column, old_value, new_value in zip(CDC_LABS_COLUMNS, old, new)
                if old_value != new_value
            ]
            if fields:
                changes.append({"change": "changed", "row": _row_label(new), "fields": fields})
        changes.extend(
            {"change": "removed", "row": _row_label(old)} for old in old_rows[len(new_rows) :]
        )
        changes.extend(
            {"change": "added", "row": _row_label(new)} for new in new_rows[len(old_rows) :]
        )
    return changes


def _cdc_labs_upstream_diff(serving_payload: bytes, candidate_payload: bytes) -> dict[str, Any]:
    serving = _rows_by_certificate(serving_payload)
    candidate = _rows_by_certificate(candidate_payload)
    serving_rows = Counter(values for rows in serving.values() for values in rows)
    candidate_rows = Counter(values for rows in candidate.values() for values in rows)

    def listed(certificates: set[str], rows: dict[str, list[tuple[str, ...]]]) -> list[dict]:
        return [
            {"certificate_no": item, "institution": rows[item][0][2], "rows": len(rows[item])}
            for item in sorted(certificates)
        ]

    # Row order inside one certificate does not count as a change.
    changed = [
        {
            "certificate_no": certificate,
            "institution": candidate[certificate][0][2],
            "changes": _certificate_changes(serving[certificate], candidate[certificate]),
        }
        for certificate in sorted(serving.keys() & candidate.keys())
        if Counter(serving[certificate]) != Counter(candidate[certificate])
    ]
    return {
        "row_counts": {
            "serving": sum(serving_rows.values()),
            "candidate": sum(candidate_rows.values()),
        },
        "certificate_counts": {"serving": len(serving), "candidate": len(candidate)},
        "added_certificates": listed(candidate.keys() - serving.keys(), candidate),
        "removed_certificates": listed(serving.keys() - candidate.keys(), serving),
        "changed_certificates": changed,
        "rows_only_in_candidate": sum((candidate_rows - serving_rows).values()),
        "rows_only_in_serving": sum((serving_rows - candidate_rows).values()),
    }


def _cdc_labs_diff_markdown(
    diff: dict[str, Any],
    *,
    checked_at: str,
    serving_id: str,
    serving_version: str,
    candidate_version: str,
) -> str:
    rows = diff["row_counts"]
    certificates = diff["certificate_counts"]
    changed = diff["changed_certificates"]
    exceeds = abs(rows["candidate"] - rows["serving"]) * 10 > rows["serving"]
    lines = [
        "# 疾管署傳染病認可檢驗機構名冊：上游有新版",
        "",
        f"- 檢查時間（UTC）：{checked_at}",
        f"- 名冊版本：服務中 {serving_version} → 新版 {candidate_version}",
        f"- 比對的服務中版本：`{serving_id}`",
        f"- 資料列：服務中 {rows['serving']:,} 列 → 新版 {rows['candidate']:,} 列",
        f"- 證號：服務中 {certificates['serving']:,} 個 → 新版 {certificates['candidate']:,} 個",
        f"- 新增證號 {len(diff['added_certificates']):,} 個、消失證號 "
        f"{len(diff['removed_certificates']):,} 個、內容有改的證號 {len(changed):,} 個",
        f"- 內容不同的資料列：新版有、舊版沒有 {diff['rows_only_in_candidate']:,} 列；"
        f"舊版有、新版沒有 {diff['rows_only_in_serving']:,} 列",
        "- 資料列變動超過 10%：" + ("是" if exceeds else "否"),
        "",
        f"## 內容有改的證號（{len(changed):,} 個）",
        "",
    ]
    words = {"added": "新增", "removed": "刪除"}
    for item in changed[:_DIFF_LIST_LIMIT]:
        parts = []
        for change in item["changes"][:_DIFF_CHANGE_LIMIT]:
            if change["change"] == "changed":
                fields = "、".join(
                    f"{field['column']} {_short(field['before'])} → {_short(field['after'])}"
                    for field in change["fields"]
                )
                parts.append(f"{change['row']}：{fields}")
            else:
                parts.append(f"{words[change['change']]} {change['row']}")
        extra = len(item["changes"]) - _DIFF_CHANGE_LIMIT
        lines.append(
            f"- {item['certificate_no']} {item['institution']}："
            + "；".join(parts)
            + (f"；另 {extra} 項" if extra > 0 else "")
        )
    if not changed:
        lines.append("（無）")
    elif len(changed) > _DIFF_LIST_LIMIT:
        lines.append(f"- …另外 {len(changed) - _DIFF_LIST_LIMIT:,} 個，完整清單見 diff.json")
    lines.append("")
    for title, items in (
        ("新增的證號", diff["added_certificates"]),
        ("消失的證號", diff["removed_certificates"]),
    ):
        lines.extend([f"## {title}（{len(items):,} 個）", ""])
        lines.extend(
            f"- {item['certificate_no']} {item['institution']}（{item['rows']:,} 列）"
            for item in items[:_DIFF_LIST_LIMIT]
        )
        if not items:
            lines.append("（無）")
        elif len(items) > _DIFF_LIST_LIMIT:
            lines.append(f"- …另外 {len(items) - _DIFF_LIST_LIMIT:,} 個，完整清單見 diff.json")
        lines.append("")
    return "\n".join(lines)


def run_cdc_labs_upstream_check(
    data_root: Path,
    *,
    actor: str,
    landing_url: str = CDC_LABS_LANDING_URL,
    opener=None,
    clock=None,
) -> dict[str, Any]:
    """Check the official page once and record the result without switching the served roster.

    The same ODS bytes as the serving build record a successful check. A different ODS keeps
    serving the current build, marks a review-pending candidate and writes a diff report. A
    failed fetch or validation keeps serving the current build and marks it stale.
    """

    from .publish import publish_operational_check
    from .sync import _write_immutable_json, _write_new_file

    data_root = Path(data_root)
    serving = _read_cdc_labs_serving(data_root)
    report = run_cdc_labs_upstream_sync(
        data_root, landing_url=landing_url, opener=opener, clock=clock
    )
    discovery = report["discovery"] or {}
    summary: dict[str, Any] = {
        "result": None,
        "sync_report_data_root_relative_path": report["report_data_root_relative_path"],
        "diff_data_root_relative_path": None,
        "diff_summary_data_root_relative_path": None,
        "candidate_raw_revision_id": None,
        "roster_version": discovery.get("roster_version_raw"),
        "failed_stage": None if report["status"] == "passed" else report["stage"],
        "error_code": report["error_code"],
        "rows": (report["summary"] or {}).get("rows"),
        "check_id": None,
        "generation": None,
        "stale": None,
        "stale_reason_codes": None,
    }
    if serving is None:
        summary["result"] = "no_serving_snapshot"
        return summary

    descriptor = serving["descriptor"]
    saved_sha256 = report["fetch"]["sha256"] if report["raw_revision_id"] else None
    seen_version = discovery["roster_version_raw"] if saved_sha256 else None
    candidate_id = None
    candidate_status = "none"
    if report["status"] != "passed":
        result = "failed"
        check_result = "failed"
        reasons = ["upstream_verification_failed"]
        if saved_sha256 is not None and saved_sha256 != serving["artifact_sha256"]:
            candidate_status = "rejected"
            candidate_id = report["raw_revision_id"]
            reasons.append("newer_candidate_rejected")
        seen_sha256 = saved_sha256 or descriptor["latest_seen_artifact_sha256"]
        seen_version = seen_version or descriptor["latest_seen_version"]
    elif saved_sha256 == serving["artifact_sha256"]:
        result = "unchanged"
        check_result = "success"
        reasons = []
        seen_sha256 = saved_sha256
    else:
        result = "changed"
        check_result = "success"
        candidate_status = "review_pending"
        candidate_id = report["raw_revision_id"]
        reasons = ["newer_candidate_pending_review"]
        seen_sha256 = saved_sha256
        diff = _cdc_labs_upstream_diff(
            _read_hashed_raw(data_root, serving["artifact_relative"], serving["artifact_sha256"]),
            _read_hashed_raw(
                data_root, report["raw_artifact_data_root_relative_path"], saved_sha256
            ),
        )
        attempt_dir = PurePosixPath(report["report_data_root_relative_path"]).parent
        diff_relative = str(attempt_dir / "diff.json")
        summary_relative = str(attempt_dir / "diff-summary.md")
        _write_immutable_json(
            data_root / PurePosixPath(diff_relative),
            {
                "diff_schema_version": 1,
                "source_id": CDC_LABS_SOURCE_ID,
                "checked_at": report["completed_at"],
                "serving_snapshot_id": serving["serving_id"],
                "serving_roster_version": serving["roster_version"],
                "serving_raw_artifact_sha256": serving["artifact_sha256"],
                "candidate_raw_revision_id": candidate_id,
                "candidate_roster_version": seen_version,
                "candidate_raw_artifact_sha256": saved_sha256,
                **diff,
            },
        )
        _write_new_file(
            data_root / PurePosixPath(summary_relative),
            _cdc_labs_diff_markdown(
                diff,
                checked_at=report["completed_at"],
                serving_id=serving["serving_id"],
                serving_version=serving["roster_version"],
                candidate_version=seen_version,
            ).encode("utf-8"),
        )
        summary["diff_data_root_relative_path"] = diff_relative
        summary["diff_summary_data_root_relative_path"] = summary_relative

    check = {
        "check_schema_version": 1,
        "check_id": f"{CDC_LABS_SOURCE_ID}-check-{report['attempt_id'].lower()}",
        "source_id": CDC_LABS_SOURCE_ID,
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
        CDC_LABS_SOURCE_ID,
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
