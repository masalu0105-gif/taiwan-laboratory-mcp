"""TFDA medical device permit dataset: upstream discovery, raw ZIP retention, validation.

Owner confirmed the source identity on 2026-09-14 (owner-review
tfda-source-identity-confirmation-2026-09-14.md). This path keeps the fetched ZIP as an
immutable raw revision and writes a staged validation report. It never creates a
candidate, curated build or current descriptor.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from .canonical import canonical_json_bytes, sha256_bytes, sha256_json
from .fetch import FetchedArtifact, FetchError, fetch_https_bytes
from .importers.tfda import (
    MAX_ZIP_BYTES,
    TFDA_PARSER_VERSION,
    TFDA_SCHEMA_VERSION,
    TFDA_SOURCE_ID,
    TFDAImportError,
    _iter_tfda_records,
    extract_tfda_csv,
    summarize_tfda_csv,
)
from .util import search_normalize

TFDA_DATASET_ID = "9576"
TFDA_SOURCE_IDENTIFIER = "A21020000I-000053"
TFDA_PUBLISHER_OID = "2.16.886.101.20003.20065.20065"
TFDA_PROVIDER = "衛生福利部食品藥物管理署"
TFDA_METADATA_URL = "https://data.gov.tw/api/v2/rest/dataset/9576"
TFDA_LANDING_URL = "https://data.gov.tw/dataset/9576"
TFDA_LICENSE_CODE = "1"
TFDA_LICENSE = "政府資料開放授權條款-第1版"
TFDA_LICENSE_URL = "https://data.gov.tw/license"
TFDA_METADATA_HOSTS = frozenset({"data.gov.tw"})
TFDA_RESOURCE_HOSTS = frozenset({"data.fda.gov.tw"})
PRIMARY_ARTIFACT_ID = "tfda-primary-zip"


def discover_tfda_resource(
    metadata_payload: bytes, *, expected_publisher_oid: str
) -> dict[str, Any]:
    try:
        document = json.loads(metadata_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FetchError("DISCOVERY_METADATA_INVALID") from exc
    if not isinstance(document, dict) or document.get("success") is not True:
        raise FetchError("DISCOVERY_METADATA_INVALID")
    result = document.get("result")
    if not isinstance(result, dict):
        raise FetchError("DISCOVERY_METADATA_INVALID")
    if not isinstance(expected_publisher_oid, str) or not expected_publisher_oid:
        raise FetchError("DISCOVERY_EXPECTATION_INVALID")
    if result.get("publisherOID") != expected_publisher_oid:
        raise FetchError("DISCOVERY_PUBLISHER_MISMATCH")
    if result.get("identifier") != TFDA_SOURCE_IDENTIFIER:
        raise FetchError("DISCOVERY_IDENTIFIER_MISMATCH")
    if result.get("license") != TFDA_LICENSE_CODE:
        raise FetchError("DISCOVERY_LICENSE_MISMATCH")

    distributions = result.get("distribution")
    matches = [
        item
        for item in (distributions if isinstance(distributions, list) else [])
        if isinstance(item, dict)
        and str(item.get("resourceFormat", "")).upper() == "CSV"
        and str(item.get("resourceCharacterEncoding", "")).upper() == "UTF-8"
        and isinstance(item.get("resourceDownloadUrl"), str)
        and item["resourceDownloadUrl"]
    ]
    if not matches:
        raise FetchError("DISCOVERY_RESOURCE_MISSING")
    if len(matches) != 1:
        raise FetchError("DISCOVERY_RESOURCE_AMBIGUOUS")
    resource_url = matches[0]["resourceDownloadUrl"]
    parsed = urlsplit(resource_url)
    host = parsed.hostname.rstrip(".").lower() if parsed.hostname else None
    if parsed.scheme.lower() != "https" or host not in TFDA_RESOURCE_HOSTS:
        raise FetchError("FETCH_HOST_NOT_ALLOWED")
    modified = result.get("modifiedDate")
    return {
        "dataset_id": TFDA_DATASET_ID,
        "identifier": TFDA_SOURCE_IDENTIFIER,
        "publisher_oid": expected_publisher_oid,
        "landing_url": TFDA_LANDING_URL,
        "metadata_url": TFDA_METADATA_URL,
        "license_code": TFDA_LICENSE_CODE,
        "license_name": TFDA_LICENSE,
        "license_url": TFDA_LICENSE_URL,
        "provider": TFDA_PROVIDER,
        "resource_format": "CSV",
        "resource_url": resource_url,
        "official_modified_at_raw": modified if isinstance(modified, str) and modified else None,
        "official_modified_timezone_known": False,
    }


def tfda_raw_revision_id(
    *, payload_sha256: str, payload_size: int, discovery: dict[str, Any]
) -> str:
    """RawRevisionFingerprintV1 for one fetched TFDA ZIP plus its non-volatile discovery."""

    return sha256_json(
        {
            "fingerprint_schema": "raw-revision-v1",
            "source_id": TFDA_SOURCE_ID,
            "discovery": {
                key: discovery.get(key)
                for key in (
                    "landing_url",
                    "publisher_oid",
                    "dataset_id",
                    "identifier",
                    "license_name",
                    "license_url",
                    "official_modified_at_raw",
                    "official_modified_timezone_known",
                )
            },
            "artifacts": [
                {
                    "artifact_id": PRIMARY_ARTIFACT_ID,
                    "role": "primary",
                    "media_type_verified": "application/zip",
                    "bytes": payload_size,
                    "sha256": payload_sha256,
                }
            ],
        }
    )


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
    revision_dir = PurePosixPath("raw", TFDA_SOURCE_ID, raw_revision_id)
    artifact_relative = str(revision_dir / "artifacts" / "source.zip")
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
                "source_id": TFDA_SOURCE_ID,
                "raw_revision_id": raw_revision_id,
                "discovery": discovery,
                "artifact": {
                    "artifact_id": PRIMARY_ARTIFACT_ID,
                    "role": "primary",
                    "data_root_relative_path": artifact_relative,
                    "media_type_verified": "application/zip",
                    **_fetch_evidence(artifact),
                },
            },
        )
    return artifact_relative, fetch_relative


def run_tfda_upstream_sync(
    data_root: Path,
    *,
    expected_publisher_oid: str,
    metadata_url: str = TFDA_METADATA_URL,
    max_zip_bytes: int = MAX_ZIP_BYTES,
    timeout_seconds: float = 60.0,
    max_redirects: int = 3,
    opener=None,
    clock=None,
) -> dict[str, Any]:
    """Discover, fetch and validate the TFDA CSV ZIP; keep raw bytes; never publish."""

    from .sync import SyncError, _attempt_id, _utc_now, _write_immutable_json

    data_root = Path(data_root)
    started_at = _utc_now(clock)
    attempt_id = _attempt_id(TFDA_SOURCE_ID, None, started_at)
    report_relative = str(PurePosixPath("staged", TFDA_SOURCE_ID, attempt_id, "validation.json"))
    stage = "discover"
    error_code = None
    discovery = None
    artifact = None
    raw_revision_id = None
    artifact_relative = None
    fetch_relative = None
    summary = None
    try:
        metadata = fetch_https_bytes(
            metadata_url,
            allowed_hosts=TFDA_METADATA_HOSTS,
            max_bytes=2 * 1024 * 1024,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            allowed_content_types={"application/json"},
            opener=opener,
            clock=clock,
        )
        discovery = discover_tfda_resource(
            metadata.payload, expected_publisher_oid=expected_publisher_oid
        )
        stage = "fetch"
        artifact = fetch_https_bytes(
            discovery["resource_url"],
            allowed_hosts=TFDA_RESOURCE_HOSTS,
            max_bytes=max_zip_bytes,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            allowed_content_types={"application/zip", "application/octet-stream"},
            opener=opener,
            clock=clock,
        )
        raw_revision_id = tfda_raw_revision_id(
            payload_sha256=artifact.sha256, payload_size=len(artifact.payload), discovery=discovery
        )
        artifact_relative, fetch_relative = _write_raw_revision(
            data_root, raw_revision_id, artifact, discovery
        )
        stage = "archive"
        entry = extract_tfda_csv(artifact.payload, max_zip_bytes=max_zip_bytes)
        stage = "parse"
        summary = summarize_tfda_csv(entry)
        stage = "validate"
    except (FetchError, SyncError, TFDAImportError) as exc:
        error_code = exc.code
        if isinstance(exc, SyncError):
            raw_revision_id = None if artifact_relative is None else raw_revision_id
    except MemoryError:
        # Keep the stage and the already-saved raw ZIP; report instead of crashing.
        error_code = "RESOURCE_EXHAUSTED"
    completed_at = _utc_now(clock)
    report = {
        "sync_report_schema_version": 1,
        "attempt_id": attempt_id,
        "source_id": TFDA_SOURCE_ID,
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
            "parser_version": TFDA_PARSER_VERSION,
            "schema_version": TFDA_SCHEMA_VERSION,
        },
        "blocking_errors": [error_code] if error_code else [],
        "summary": summary,
        "report_data_root_relative_path": report_relative,
    }
    _write_immutable_json(data_root / PurePosixPath(report_relative), report)
    return report


_DIFF_LIST_LIMIT = 50


def _read_tfda_serving(data_root: Path) -> dict[str, Any] | None:
    from .sync import SyncError

    descriptor_path = data_root / "manifests" / "current" / f"{TFDA_SOURCE_ID}.json"
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
        artifact = json.loads(manifest_bytes.decode("utf-8"))["artifacts"][0]
        return {
            "descriptor": descriptor,
            "serving_id": serving_id,
            "artifact_sha256": artifact["sha256"],
            "artifact_relative": artifact["data_root_relative_path"],
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


def _permit_rows(payload: bytes) -> tuple[Counter[str], set[str]]:
    """Rows per normalized permit number and every source row hash of one raw ZIP."""

    permits: Counter[str] = Counter()
    hashes: set[str] = set()
    for _, values in _iter_tfda_records(extract_tfda_csv(payload).payload):
        permits[search_normalize(values[0])] += 1
        hashes.add(sha256_bytes(canonical_json_bytes(list(values))))
    return permits, hashes


def _exceeds_ten_percent(before: int, after: int) -> bool:
    return abs(after - before) * 10 > before


def _tfda_upstream_diff(serving_payload: bytes, candidate_payload: bytes) -> dict[str, Any]:
    # Parse one file at a time; each official file is about 70 MB of CSV text.
    serving_permits, serving_hashes = _permit_rows(serving_payload)
    candidate_permits, candidate_hashes = _permit_rows(candidate_payload)
    serving_rows = sum(serving_permits.values())
    candidate_rows = sum(candidate_permits.values())
    return {
        "row_counts": {"serving": serving_rows, "candidate": candidate_rows},
        "permit_counts": {"serving": len(serving_permits), "candidate": len(candidate_permits)},
        "added_permits": sorted(candidate_permits.keys() - serving_permits.keys()),
        "removed_permits": sorted(serving_permits.keys() - candidate_permits.keys()),
        "rows_only_in_candidate": len(candidate_hashes - serving_hashes),
        "rows_only_in_serving": len(serving_hashes - candidate_hashes),
        "review_gate": {
            "row_count_change_exceeds_10_percent": _exceeds_ten_percent(
                serving_rows, candidate_rows
            ),
            "permit_count_change_exceeds_10_percent": _exceeds_ten_percent(
                len(serving_permits), len(candidate_permits)
            ),
        },
    }


def _tfda_diff_markdown(diff: dict[str, Any], *, checked_at: str, serving_id: str) -> str:
    gate = diff["review_gate"]
    lines = [
        "# 食藥署醫療器材許可證資料：上游有新版（等待審核）",
        "",
        f"- 檢查時間（UTC）：{checked_at}",
        f"- 目前 MCP 服務中的版本：`{serving_id}`",
        f"- 資料列：服務中 {diff['row_counts']['serving']:,} 列 → 新版 {diff['row_counts']['candidate']:,} 列",
        f"- 許可證字號：服務中 {diff['permit_counts']['serving']:,} 個 → 新版 {diff['permit_counts']['candidate']:,} 個",
        f"- 新增字號 {len(diff['added_permits']):,} 個、消失字號 {len(diff['removed_permits']):,} 個",
        f"- 內容不同的資料列：新版有、舊版沒有 {diff['rows_only_in_candidate']:,} 列；"
        f"舊版有、新版沒有 {diff['rows_only_in_serving']:,} 列",
        "- 資料列變動超過 10%：" + ("是" if gate["row_count_change_exceeds_10_percent"] else "否"),
        "",
        "新版審核並發布之前，MCP 會繼續回目前的版本，並標示「有新版等待審核」。",
        "",
    ]
    for title, permits in (
        ("新增的許可證字號", diff["added_permits"]),
        ("消失的許可證字號", diff["removed_permits"]),
    ):
        lines.extend([f"## {title}（{len(permits):,} 個）", ""])
        lines.extend(f"- {permit}" for permit in permits[:_DIFF_LIST_LIMIT])
        if not permits:
            lines.append("（無）")
        elif len(permits) > _DIFF_LIST_LIMIT:
            lines.append(f"- …另外 {len(permits) - _DIFF_LIST_LIMIT:,} 個，完整清單見 diff.json")
        lines.append("")
    return "\n".join(lines)


def run_tfda_upstream_check(
    data_root: Path,
    *,
    expected_publisher_oid: str,
    actor: str,
    opener=None,
    clock=None,
) -> dict[str, Any]:
    """Check upstream once and record the result without switching the serving snapshot.

    Same ZIP bytes as the serving build record a successful check. A different ZIP keeps
    serving the approved build, marks a review-pending candidate and writes a diff report.
    A failed fetch or validation keeps serving the approved build and marks it stale.
    """

    from .publish import publish_operational_check
    from .sync import _write_immutable_json, _write_new_file

    data_root = Path(data_root)
    serving = _read_tfda_serving(data_root)
    report = run_tfda_upstream_sync(
        data_root, expected_publisher_oid=expected_publisher_oid, opener=opener, clock=clock
    )
    summary: dict[str, Any] = {
        "result": None,
        "sync_report_data_root_relative_path": report["report_data_root_relative_path"],
        "diff_data_root_relative_path": None,
        "diff_summary_data_root_relative_path": None,
        "candidate_raw_revision_id": None,
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
        diff = _tfda_upstream_diff(
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
                "source_id": TFDA_SOURCE_ID,
                "checked_at": report["completed_at"],
                "serving_snapshot_id": serving["serving_id"],
                "serving_raw_artifact_sha256": serving["artifact_sha256"],
                "candidate_raw_revision_id": candidate_id,
                "candidate_raw_artifact_sha256": saved_sha256,
                **diff,
            },
        )
        _write_new_file(
            data_root / PurePosixPath(summary_relative),
            _tfda_diff_markdown(
                diff, checked_at=report["completed_at"], serving_id=serving["serving_id"]
            ).encode("utf-8"),
        )
        summary["diff_data_root_relative_path"] = diff_relative
        summary["diff_summary_data_root_relative_path"] = summary_relative

    check = {
        "check_schema_version": 1,
        "check_id": f"{TFDA_SOURCE_ID}-check-{report['attempt_id'].lower()}",
        "source_id": TFDA_SOURCE_ID,
        "generation": descriptor["generation"] + 1,
        "serving_snapshot_id": serving["serving_id"],
        "serving_curated_build_id": serving["serving_id"],
        "checked_at": report["completed_at"],
        "latest_seen_version": None,
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
        TFDA_SOURCE_ID,
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
