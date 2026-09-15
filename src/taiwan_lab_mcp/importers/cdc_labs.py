"""CDC recognized laboratory roster: curated SQLite build and the AI-delegated official build.

SDD 10.4. Owner 2026-09-15 delegated every CDC review to AI (「Ai全程代審 不用特別備注未經人工審核」,
OD-04). A build keeps every parsed method row with its sheet name, spreadsheet row number and row
hash. The official build needs the four ODS gates signed by the reviewer the protocol names and at
least ten approved golden cases that pass against the raw ODS.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

from ..audit import _sha256_file, compute_review_subject_digest
from ..canonical import canonical_json_bytes, sha256_bytes, sha256_json
from ..models import GoldenCaseV1
from ..publish import publish_current_descriptor
from ..util import tfda_search_normalize
from .cdc_ods import (
    CDC_LABS_COLUMNS,
    CDC_LABS_FIELD_NAMES,
    CDC_LABS_PARSER_VERSION,
    CDC_LABS_SCHEMA_VERSION,
    CDC_LABS_SOURCE_ID,
    DEFAULT_ODS_LIMITS,
    ODS_MIMETYPE,
    CdcLabRow,
    CdcLabsParseResult,
    CdcOdsImportError,
    parse_cdc_labs_ods,
)

CDC_LABS_PRIMARY_ARTIFACT_ID = "cdc-labs-primary-ods"
CDC_LABS_PROVIDER = "衛生福利部疾病管制署"
CDC_LABS_DATASET_NAME = "傳染病認可檢驗機構名冊"
CDC_LABS_ATTRIBUTION = "資料提供機關：衛生福利部疾病管制署"
CDC_LABS_NORMALIZATION_VERSION = "cdc-text-v1"
CDC_LABS_FRESHNESS_POLICY_VERSION = "cdc-labs-v1"
CDC_LABS_TABLE = "cdc_lab_row"
CDC_LABS_SERVING_GATES = ("ODS-R1-SOURCE", "ODS-R1-STRUCTURE", "ODS-R1-CONTENT", "PUB-R1-OWNER")
# Owner 2026-09-15: 「Ai全程代審 不用特別備注未經人工審核」.
CDC_LABS_REVIEW_PROTOCOL_ID = "cdc-labs-r1-ai-review"
CDC_LABS_REVIEW_PROTOCOL_VERSION = "1"
_DELEGATED_REVIEW_PROTOCOLS = frozenset(
    {(CDC_LABS_REVIEW_PROTOCOL_ID, CDC_LABS_REVIEW_PROTOCOL_VERSION)}
)
_ODS_MEDIA_TYPE = ODS_MIMETYPE.decode("ascii")
_MINIMUM_OFFICIAL_GOLDEN_CASES = 10
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
_OWNER_REVIEW_KEYS = frozenset(
    {"gate_id", "reviewer_id", "reviewer_role", "reviewed_at", "finding_counts", "comments"}
)
SEARCH_COLUMNS = (
    ("certificate_search", "certificate_no"),
    ("city_search", "city"),
    ("institution_search", "institution"),
    ("department_search", "department"),
    ("disease_code_search", "disease_code"),
    ("disease_name_search", "disease_name"),
    ("purpose_search", "purpose"),
    ("method_search", "method"),
)
CDC_LABS_ROW_COLUMNS = (
    "source_row_sha256",
    "expanded_row_number",
    "sheet_name",
    *CDC_LABS_FIELD_NAMES,
    *(column for column, _ in SEARCH_COLUMNS),
)
_TABLE_SQL = "CREATE TABLE {} ({})".format(
    CDC_LABS_TABLE,
    ", ".join(
        f"{column} INTEGER NOT NULL"
        if column == "expanded_row_number"
        else f"{column} TEXT NOT NULL"
        for column in CDC_LABS_ROW_COLUMNS
    ),
)
_INDEX_SQL = (
    f"CREATE UNIQUE INDEX cdc_lab_row_number ON {CDC_LABS_TABLE} (expanded_row_number)",
    f"CREATE INDEX cdc_lab_row_certificate ON {CDC_LABS_TABLE} "
    "(certificate_search, expanded_row_number)",
)
_INSERT_SQL = "INSERT INTO {} ({}) VALUES ({})".format(
    CDC_LABS_TABLE,
    ", ".join(CDC_LABS_ROW_COLUMNS),
    ", ".join("?" for _ in CDC_LABS_ROW_COLUMNS),
)


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def curated_lab_row(row: CdcLabRow, sheet_name: str) -> dict[str, Any]:
    """Return the stored columns: raw values unchanged plus search columns."""

    fields = row.fields()
    curated: dict[str, Any] = {
        "source_row_sha256": row.source_row_sha256,
        "expanded_row_number": row.expanded_row_number,
        "sheet_name": sheet_name,
        **fields,
    }
    for column, field in SEARCH_COLUMNS:
        curated[column] = tfda_search_normalize(fields[field])
    return curated


def _write_curated_db(db_path: Path, parsed: CdcLabsParseResult) -> None:
    if db_path.exists():
        raise CdcOdsImportError("IMMUTABLE_BUILD_EXISTS")
    partial = db_path.with_name(f".{db_path.name}.partial")
    if partial.exists():
        partial.unlink()
    connection = sqlite3.connect(partial)
    succeeded = False
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute(_TABLE_SQL)
        connection.executemany(
            _INSERT_SQL,
            [
                tuple(row[column] for column in CDC_LABS_ROW_COLUMNS)
                for row in (curated_lab_row(item, parsed.sheet_name) for item in parsed.rows)
            ],
        )
        for statement in _INDEX_SQL:
            connection.execute(statement)
        connection.commit()
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise CdcOdsImportError("SQLITE_INTEGRITY_FAILURE")
        succeeded = True
    except sqlite3.IntegrityError as exc:
        raise CdcOdsImportError("DUPLICATE_SOURCE_ROW") from exc
    finally:
        connection.close()
        if not succeeded and partial.exists():
            partial.unlink()
    os.replace(partial, db_path)


def active_cdc_labs_transform() -> dict[str, Any]:
    """Return the parser/schema/normalization identity a golden case must bind to."""

    return {
        "parser": {
            "version": CDC_LABS_PARSER_VERSION,
            "bundle_sha256": sha256_json(
                {"columns": list(CDC_LABS_COLUMNS), "limits": asdict(DEFAULT_ODS_LIMITS)}
            ),
        },
        "schema": {
            "version": CDC_LABS_SCHEMA_VERSION,
            "bundle_sha256": sha256_json(
                {"columns": list(CDC_LABS_COLUMNS), "curated_columns": list(CDC_LABS_ROW_COLUMNS)}
            ),
        },
        "normalization": {
            "version": CDC_LABS_NORMALIZATION_VERSION,
            "bundle_sha256": sha256_json({"rule": "NFKC-casefold-whitespace-quotes-tai"}),
        },
        "rules": [],
        "qualifier": {
            "name": None,
            "version": None,
            "spec_sha256": None,
            "extractor_output_sha256": None,
        },
    }


def _golden_failure_codes(
    case: GoldenCaseV1,
    rows_by_number: Mapping[int, CdcLabRow],
    *,
    sheet_name: str,
    raw_artifact_sha256: str,
    transform: dict[str, Any],
) -> list[str]:
    codes: list[str] = []
    if case.source_id != CDC_LABS_SOURCE_ID:
        codes.append("SOURCE_MISMATCH")
    if (
        case.artifact_id != CDC_LABS_PRIMARY_ARTIFACT_ID
        or case.raw_artifact_sha256 != raw_artifact_sha256
    ):
        codes.append("ARTIFACT_MISMATCH")
    if case.transform != transform:
        codes.append("TRANSFORM_MISMATCH")
    if case.expected_status != "ok":
        codes.append("EXPECTED_STATUS_UNSUPPORTED")
    locator = case.source_locator
    if locator.locator_type != "ods_row":
        codes.append("LOCATOR_UNSUPPORTED")
    if not case.expected_fields:
        codes.append("EXPECTED_FIELDS_EMPTY")
    codes.extend(
        f"EXPECTED_FIELD_UNSUPPORTED:{field}"
        for field in sorted(set(case.expected_fields) - set(CDC_LABS_FIELD_NAMES))
    )
    certificate = (
        case.input.get("certificate_no") if set(case.input) == {"certificate_no"} else None
    )
    if not certificate:
        codes.append("INPUT_UNSUPPORTED")
        return codes
    row = (
        rows_by_number.get(locator.expanded_row_number)
        if locator.locator_type == "ods_row" and locator.sheet_name == sheet_name
        else None
    )
    if row is None or row.fields()["certificate_no"] != certificate:
        codes.append("STATUS_MISMATCH")
        return codes
    if case.source_row_sha256 != row.source_row_sha256:
        codes.append("LOCATOR_MISMATCH")
    fields = row.fields()
    codes.extend(
        f"FIELD_MISMATCH:{field}"
        for field in sorted(set(case.expected_fields) & set(CDC_LABS_FIELD_NAMES))
        if case.expected_fields[field] != fields[field]
    )
    if case.expected_warnings:
        codes.append("WARNINGS_MISMATCH")
    return codes


def _golden_results(
    parsed: CdcLabsParseResult,
    cases: Sequence[Mapping[str, Any]],
    *,
    raw_artifact_sha256: str,
) -> list[dict[str, Any]]:
    validated: list[tuple[dict[str, Any], GoldenCaseV1]] = []
    try:
        for case in cases:
            case_bytes = canonical_json_bytes(dict(case))
            validated.append((json.loads(case_bytes), GoldenCaseV1.model_validate_json(case_bytes)))
    except (TypeError, ValueError) as exc:
        raise CdcOdsImportError("GOLDEN_CASE_SCHEMA_INVALID") from exc
    case_ids = [model.case_id for _, model in validated]
    if len(set(case_ids)) != len(case_ids):
        raise CdcOdsImportError("GOLDEN_CASE_SCHEMA_INVALID", "duplicate case_id")
    rows_by_number = {row.expanded_row_number: row for row in parsed.rows}
    transform = active_cdc_labs_transform()
    results = []
    for raw_case, model in validated:
        failure_codes = _golden_failure_codes(
            model,
            rows_by_number,
            sheet_name=parsed.sheet_name,
            raw_artifact_sha256=raw_artifact_sha256,
            transform=transform,
        )
        results.append(
            {
                "golden_case": raw_case,
                "golden_case_sha256": sha256_bytes(canonical_json_bytes(raw_case)),
                "evaluation_status": "failed" if failure_codes else "passed",
                "failure_codes": failure_codes,
            }
        )
    return results


def evaluate_cdc_labs_golden_cases(
    payload: bytes, cases: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Re-run golden cases against raw ODS bytes; no network, writes or approval."""

    return _golden_results(
        parse_cdc_labs_ods(payload), cases, raw_artifact_sha256=sha256_bytes(payload)
    )


def _write_audit_json(path: Path, value: Mapping[str, Any]) -> str:
    payload = canonical_json_bytes(dict(value))
    if path.exists():
        if path.read_bytes() != payload:
            raise CdcOdsImportError("IMMUTABLE_AUDIT_CONFLICT")
        return sha256_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return sha256_bytes(payload)


def _current_generation(data_root: Path) -> tuple[int, str | None]:
    current_path = data_root / "manifests" / "current" / f"{CDC_LABS_SOURCE_ID}.json"
    if not current_path.is_file():
        return 0, None
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
        return int(current["generation"]), current["serving_snapshot_id"]
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise CdcOdsImportError("CURRENT_POINTER_INTEGRITY") from exc


def _publish_build(
    data_root: Path,
    *,
    payload: bytes,
    parsed: CdcLabsParseResult,
    raw_revision_id: str,
    artifact_relative: str,
    fetch_relative: str | None,
    discovery: Mapping[str, Any],
    fetched_at: str,
    application_build_hash: str,
    golden_results: list[dict[str, Any]],
    review_inputs: Sequence[Mapping[str, Any]],
    protocol: tuple[str, str, str],
    publisher_actor_id: str,
    evidence_inputs: Sequence[tuple[str, str, bytes]],
    official: bool,
    pre_publish_check: Callable[[Path], tuple[str, str, bytes]] | None = None,
) -> dict[str, Any]:
    """Write the curated build and its audit bundle, then publish it with generation CAS."""

    raw_digest = sha256_bytes(payload)
    transform = active_cdc_labs_transform()
    build_fingerprint = {
        "fingerprint_schema": "curated-build-v1",
        "source_id": CDC_LABS_SOURCE_ID,
        "raw_revision_id": raw_revision_id,
        "application_build_sha256": application_build_hash,
        **transform,
    }
    build_hash = sha256_json(build_fingerprint)
    build_id = f"{CDC_LABS_SOURCE_ID}-build-{build_hash}"
    build_prefix = f"curated/{CDC_LABS_SOURCE_ID}/{build_id}"
    build_dir = data_root / PurePosixPath(build_prefix)
    if build_dir.exists():
        raise CdcOdsImportError("IMMUTABLE_BUILD_EXISTS")
    expected_generation, expected_parent = _current_generation(data_root)

    build_dir.mkdir(parents=True)
    db_relative = f"{build_prefix}/data.sqlite3"
    db_path = data_root / PurePosixPath(db_relative)
    _write_curated_db(db_path, parsed)
    db_digest = _sha256_file(db_path)
    if pre_publish_check is not None:
        # Runs on the finished database before any audit record or pointer refers to it.
        evidence_inputs = [*evidence_inputs, pre_publish_check(db_path)]
    audit_prefix = f"{build_prefix}/audit"
    rows = len(parsed.rows)
    row_counts = {"input_rows": rows, "curated_rows": rows, "quarantined_rows": 0}
    artifact_hashes = [
        {"artifact_id": CDC_LABS_PRIMARY_ARTIFACT_ID, "role": "primary", "sha256": raw_digest}
    ]
    synthetic_ci_status = "not_run" if official else "passed"
    validation = {
        "validation_schema_version": 1,
        "source_id": CDC_LABS_SOURCE_ID,
        "raw_revision_id": raw_revision_id,
        "curated_build_id": build_id,
        "build_fingerprint_sha256": build_hash,
        "curated_db_sha256": db_digest,
        "artifact_hashes": artifact_hashes,
        "row_counts": row_counts,
        "automated_status": "passed",
        "synthetic_ci_status": synthetic_ci_status,
        "blocking_errors": [],
        "warnings": [],
    }
    case_ids = [result["golden_case"]["case_id"] for result in golden_results]
    candidate = {
        "qualification_candidate_schema_version": 1,
        "source_id": CDC_LABS_SOURCE_ID,
        "raw_revision_id": raw_revision_id,
        "curated_build_id": build_id,
        "case_ids": case_ids,
        "case_count": len(golden_results),
        "cases": golden_results,
        "input_artifact_hashes": artifact_hashes,
        "curated_db_sha256": db_digest,
        "active_transform": transform,
        "automated_status": "passed",
        "synthetic_ci_status": synthetic_ci_status,
        "official_qualification_status": "not_qualified",
        "note": (
            "pre-review candidate for an AI-reviewed official CDC roster build"
            if official
            else "offline synthetic fixture; not official qualification evidence"
        ),
    }
    validation_relative = f"{audit_prefix}/validation.json"
    candidate_relative = f"{audit_prefix}/qualification-candidate.json"
    validation_digest = _write_audit_json(
        data_root / PurePosixPath(validation_relative), validation
    )
    candidate_digest = _write_audit_json(data_root / PurePosixPath(candidate_relative), candidate)

    manifest: dict[str, Any] = {
        "manifest_schema_version": 1,
        "snapshot_id": build_id,
        "raw_revision_id": raw_revision_id,
        "curated_build_id": build_id,
        "build_fingerprint_sha256": build_hash,
        "build_fingerprint": build_fingerprint,
        "discovery_metadata_sha256": sha256_json(dict(discovery)),
        "review_subject_digest": None,
        "source_id": CDC_LABS_SOURCE_ID,
        "state": "approved",
        "source": {
            "provider": CDC_LABS_PROVIDER,
            "dataset_name": CDC_LABS_DATASET_NAME,
            "landing_url": discovery["landing_url"],
            "resource_url": discovery["resource_url"],
            "attachment_label": discovery["attachment_label"],
            "license_name": discovery["license_name"],
            "license_url": discovery["license_url"],
            "attribution": CDC_LABS_ATTRIBUTION,
        },
        "official_version": {
            "label": discovery["roster_version_raw"],
            "modified_at_raw": None,
            "modified_at_precision": "unknown",
            "timezone_known": False,
        },
        "fetched_at": fetched_at,
        "artifacts": [
            {
                "artifact_id": CDC_LABS_PRIMARY_ARTIFACT_ID,
                "role": "primary",
                "resource_url": discovery["resource_url"],
                "storage_scope": "data_root",
                "data_root_relative_path": artifact_relative,
                "local_artifact_available": True,
                "media_type_verified": _ODS_MEDIA_TYPE,
                "bytes": len(payload),
                "sha256": raw_digest,
            }
        ],
        "transform": {"application_build_sha256": application_build_hash, **transform},
        "counts": row_counts,
        "validation": {
            "automated_validation_status": "passed",
            "blocking_errors": [],
            "warnings": [],
        },
        "review": {
            "human_review_status": "approved",
            "required_gates": list(CDC_LABS_SERVING_GATES),
            "completed_gates": list(CDC_LABS_SERVING_GATES),
            "capability_reviews": [],
        },
        "roster_summary": parsed.summary,
        "audit_evidence": {
            "validation": {
                "data_root_relative_path": validation_relative,
                "sha256": validation_digest,
            },
            "qualification_candidate": {
                "data_root_relative_path": candidate_relative,
                "sha256": candidate_digest,
            },
            "golden_qualification": None,
            "reviews": [],
        },
        "publication": {"curated_build_relative_path": db_relative, "curated_sha256": db_digest},
    }
    evidence_refs = [
        {
            "artifact_id": CDC_LABS_PRIMARY_ARTIFACT_ID,
            "path": artifact_relative,
            "locator": {"kind": "source_artifact"},
            "sha256": raw_digest,
        }
    ]
    if fetch_relative is not None:
        fetch_digest = _sha256_file(data_root / PurePosixPath(fetch_relative))
        manifest["discovery"] = {"data_root_relative_path": fetch_relative, "sha256": fetch_digest}
        evidence_refs.append(
            {
                "artifact_id": "cdc-labs-fetch-record",
                "path": fetch_relative,
                "locator": {"kind": "fetch_record"},
                "sha256": fetch_digest,
            }
        )
    subject_digest = compute_review_subject_digest(
        manifest,
        curated_db_sha256=db_digest,
        validation_report_sha256=validation_digest,
        qualification_candidate_sha256=candidate_digest,
    )
    manifest["review_subject_digest"] = subject_digest
    evidence_refs.extend(
        [
            {
                "artifact_id": "cdc-labs-curated-db",
                "path": db_relative,
                "locator": {"kind": "sqlite_snapshot"},
                "sha256": db_digest,
            },
            {
                "artifact_id": "cdc-labs-validation",
                "path": validation_relative,
                "locator": {"kind": "validation_report"},
                "sha256": validation_digest,
            },
            {
                "artifact_id": "cdc-labs-qualification-candidate",
                "path": candidate_relative,
                "locator": {"kind": "qualification_candidate"},
                "sha256": candidate_digest,
            },
        ]
    )
    for artifact_id, name, content in evidence_inputs:
        evidence_relative = f"{audit_prefix}/evidence/{name}"
        evidence_path = data_root / PurePosixPath(evidence_relative)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_bytes(content)
        evidence_refs.append(
            {
                "artifact_id": artifact_id,
                "path": evidence_relative,
                "locator": {"kind": "owner_review_evidence"},
                "sha256": sha256_bytes(content),
            }
        )

    protocol_id, protocol_version, protocol_sha256 = protocol
    for review_input in review_inputs:
        gate_id = review_input["gate_id"]
        review = {
            "review_schema_version": 1,
            "gate_id": gate_id,
            "decision": "approved",
            "source_id": CDC_LABS_SOURCE_ID,
            "curated_build_id": build_id,
            "subject_digest": subject_digest,
            "reviewer_id": review_input["reviewer_id"],
            "reviewer_role": review_input["reviewer_role"],
            "identity_assurance": "local_asserted",
            "reviewed_at": review_input["reviewed_at"],
            "protocol_id": protocol_id,
            "protocol_version": protocol_version,
            "protocol_sha256": protocol_sha256,
            "review_scope": (
                {
                    "kind": "owner_review",
                    "protocol_section": gate_id,
                    "row_count": rows,
                    "golden_case_ids": case_ids,
                }
                if official
                else {"kind": "synthetic_fixture", "row_count": rows}
            ),
            "evidence_refs": evidence_refs,
            "finding_counts": dict(review_input["finding_counts"]),
            "comments": review_input["comments"],
            "signature": None,
        }
        review_relative = f"{audit_prefix}/reviews/{gate_id}.json"
        manifest["audit_evidence"]["reviews"].append(
            {
                "gate_id": gate_id,
                "data_root_relative_path": review_relative,
                "sha256": _write_audit_json(data_root / PurePosixPath(review_relative), review),
            }
        )
    certificate = {
        "qualification_certificate_schema_version": 1,
        "source_id": CDC_LABS_SOURCE_ID,
        "curated_build_id": build_id,
        "subject_digest": subject_digest,
        "candidate_report_sha256": candidate_digest,
        "accepted_review_hashes": [
            item["sha256"] for item in manifest["audit_evidence"]["reviews"]
        ],
        "approved_distinct_case_ids": case_ids if official else [],
        "official_qualification_status": "approved" if official else "not_qualified",
    }
    certificate_relative = f"{audit_prefix}/golden-qualification.json"
    manifest["audit_evidence"]["golden_qualification"] = {
        "data_root_relative_path": certificate_relative,
        "sha256": _write_audit_json(data_root / PurePosixPath(certificate_relative), certificate),
    }
    manifest_relative = f"{build_prefix}/manifest.json"
    manifest_digest = _write_audit_json(data_root / PurePosixPath(manifest_relative), manifest)

    generation = expected_generation + 1
    checked_at = _utc_now_text()
    check_id = f"{CDC_LABS_SOURCE_ID}-check-{build_hash}-g{generation}"
    check_relative = f"checks/{CDC_LABS_SOURCE_ID}/{check_id}.json"
    operational = {
        "latest_seen_version": discovery["roster_version_raw"],
        "latest_seen_artifact_sha256": raw_digest,
        "latest_candidate_id": None,
        "latest_candidate_status": "none",
        "check_result": "success",
        "failed_stage": None,
        "error_code": None,
        "stale": False,
        "stale_reason_codes": [],
        "freshness_policy_version": CDC_LABS_FRESHNESS_POLICY_VERSION,
        "content_age_status": "unknown",
        "content_age_evidence": None,
    }
    check = {
        "check_schema_version": 1,
        "check_id": check_id,
        "source_id": CDC_LABS_SOURCE_ID,
        "generation": generation,
        "serving_snapshot_id": build_id,
        "serving_curated_build_id": build_id,
        "checked_at": checked_at,
        **operational,
    }
    check_digest = _write_audit_json(data_root / PurePosixPath(check_relative), check)
    descriptor = {
        "descriptor_schema_version": 1,
        "source_id": CDC_LABS_SOURCE_ID,
        "generation": generation,
        "serving_snapshot_id": build_id,
        "serving_curated_build_id": build_id,
        "manifest_data_root_relative_path": manifest_relative,
        "manifest_sha256": manifest_digest,
        "parent_snapshot_id": expected_parent,
        "last_successful_publish_at": checked_at,
        "publisher_actor_id": publisher_actor_id,
        "last_check_at": checked_at,
        "last_successful_check_at": checked_at,
        **operational,
        "latest_check_data_root_relative_path": check_relative,
        "latest_check_sha256": check_digest,
    }
    event = publish_current_descriptor(
        data_root,
        descriptor,
        expected_generation=expected_generation,
        expected_parent_snapshot_id=expected_parent,
        actor=publisher_actor_id,
    )
    return {
        "snapshot_id": build_id,
        "raw_revision_id": raw_revision_id,
        "rows": rows,
        "db_sha256": db_digest,
        "manifest_sha256": manifest_digest,
        "generation": generation,
        "publish_event_id": event["event_id"],
    }


def build_cdc_labs_snapshot(payload: bytes, data_root: Path) -> dict[str, Any]:
    """Build and serve a synthetic roster snapshot from caller-supplied ODS bytes.

    Offline and test-only: its reviews are offline-test-builder fixtures, never official
    source qualification.
    """

    from ..cdc_source import (
        CDC_LABS_LANDING_URL,
        CDC_LICENSE_NAME,
        CDC_LICENSE_URL,
        cdc_labs_raw_revision_id,
    )
    from .nhi import _application_build_identity

    data_root = Path(data_root)
    parsed = parse_cdc_labs_ods(payload)
    version = parsed.sheet_name.removesuffix("名冊")
    discovery = {
        "landing_url": CDC_LABS_LANDING_URL,
        "resource_url": "https://www.cdc.gov.tw/File/Get/offline-synthetic-fixture",
        "attachment_label": f"傳染病認可檢驗機構名冊{version}.ods",
        "roster_version_raw": version,
        "license_name": CDC_LICENSE_NAME,
        "license_url": CDC_LICENSE_URL,
    }
    raw_digest = sha256_bytes(payload)
    raw_revision_id = cdc_labs_raw_revision_id(
        payload_sha256=raw_digest, payload_size=len(payload), discovery=discovery
    )
    artifact_relative = f"raw/{CDC_LABS_SOURCE_ID}/{raw_revision_id}/artifacts/source.ods"
    raw_path = data_root / PurePosixPath(artifact_relative)
    if raw_path.exists():
        if raw_path.read_bytes() != payload:
            raise CdcOdsImportError("IMMUTABLE_RAW_CONFLICT")
    else:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(payload)
    fetched_at = _utc_now_text()
    review_inputs = [
        {
            "gate_id": gate_id,
            "reviewer_id": "offline-test-builder",
            "reviewer_role": "test_fixture_reviewer",
            "reviewed_at": fetched_at,
            "finding_counts": {"critical": 0, "major": 0, "minor": 0},
            "comments": "Synthetic fixture review only; not official source qualification.",
        }
        for gate_id in CDC_LABS_SERVING_GATES
    ]
    return _publish_build(
        data_root,
        payload=payload,
        parsed=parsed,
        raw_revision_id=raw_revision_id,
        artifact_relative=artifact_relative,
        fetch_relative=None,
        discovery=discovery,
        fetched_at=fetched_at,
        application_build_hash=_application_build_identity()[1],
        golden_results=[],
        review_inputs=review_inputs,
        protocol=(
            "cdc-labs-r1-synthetic-fixture",
            "1",
            sha256_json({"protocol_id": "cdc-labs-r1-synthetic-fixture", "protocol_version": "1"}),
        ),
        publisher_actor_id="offline-test-builder",
        evidence_inputs=(),
        official=False,
    )


def _review_protocol(protocol_id: str, protocol_version: str) -> tuple[str, str, str, str, str]:
    """Return protocol id, version, SHA-256 and the reviewer id and role it names."""

    if (protocol_id, protocol_version) not in _DELEGATED_REVIEW_PROTOCOLS:
        raise CdcOdsImportError("REVIEW_PROTOCOL_INVALID")
    try:
        payload = (
            files("taiwan_lab_mcp")
            .joinpath("review_protocols", protocol_id, f"{protocol_version}.json")
            .read_bytes()
        )
        document = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise CdcOdsImportError("REVIEW_PROTOCOL_INVALID") from exc
    if (
        not isinstance(document, dict)
        or document.get("protocol_id") != protocol_id
        or document.get("protocol_version") != protocol_version
        or document.get("status") != "owner_delegated"
        or sorted(document.get("gates", {})) != sorted(CDC_LABS_SERVING_GATES)
        or not isinstance(document.get("reviewer_id"), str)
        or not document["reviewer_id"]
        or not isinstance(document.get("reviewer_role"), str)
        or not document["reviewer_role"]
    ):
        raise CdcOdsImportError("REVIEW_PROTOCOL_INVALID")
    return (
        protocol_id,
        protocol_version,
        sha256_bytes(payload),
        document["reviewer_id"],
        document["reviewer_role"],
    )


def _load_official_raw_revision(
    data_root: Path, raw_revision_id: str
) -> tuple[bytes, dict[str, Any], str, str]:
    """Read one fetched roster revision and prove its bytes still match fetch.json."""

    from ..cdc_source import cdc_labs_raw_revision_id

    if not isinstance(raw_revision_id, str) or not _HEX64_RE.fullmatch(raw_revision_id):
        raise CdcOdsImportError("RAW_REVISION_INTEGRITY", "raw revision id is invalid")
    revision_dir = PurePosixPath("raw", CDC_LABS_SOURCE_ID, raw_revision_id)
    artifact_relative = str(revision_dir / "artifacts" / "source.ods")
    fetch_relative = str(revision_dir / "fetch.json")
    try:
        payload = (data_root / PurePosixPath(artifact_relative)).read_bytes()
        fetch_bytes = (data_root / PurePosixPath(fetch_relative)).read_bytes()
        fetch_record = json.loads(fetch_bytes.decode("utf-8"))
        artifact = fetch_record["artifact"]
        discovery = fetch_record["discovery"]
        recomputed = cdc_labs_raw_revision_id(
            payload_sha256=sha256_bytes(payload), payload_size=len(payload), discovery=discovery
        )
    except (KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, AttributeError) as exc:
        raise CdcOdsImportError("RAW_REVISION_INTEGRITY", "raw revision is unreadable") from exc
    required_discovery = (
        "landing_url",
        "resource_url",
        "attachment_label",
        "roster_version_raw",
        "license_name",
        "license_url",
    )
    if (
        canonical_json_bytes(fetch_record) != fetch_bytes
        or fetch_record.get("fetch_record_schema_version") != 1
        or fetch_record.get("source_id") != CDC_LABS_SOURCE_ID
        or fetch_record.get("raw_revision_id") != raw_revision_id
        or not isinstance(artifact, dict)
        or artifact.get("data_root_relative_path") != artifact_relative
        or artifact.get("sha256") != sha256_bytes(payload)
        or artifact.get("bytes") != len(payload)
        or artifact.get("media_type_verified") != _ODS_MEDIA_TYPE
        or not isinstance(artifact.get("fetched_at"), str)
        or recomputed != raw_revision_id
        or any(
            not isinstance(discovery.get(key), str) or not discovery[key]
            for key in required_discovery
        )
    ):
        raise CdcOdsImportError(
            "RAW_REVISION_INTEGRITY", "raw revision does not match fetch record"
        )
    return payload, fetch_record, artifact_relative, fetch_relative


def _validated_owner_reviews(owner_reviews: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    reviews = [dict(review) for review in owner_reviews]
    if [review.get("gate_id") for review in reviews] != list(CDC_LABS_SERVING_GATES):
        raise CdcOdsImportError("OWNER_REVIEW_GATES_INVALID")
    for review in reviews:
        counts = review.get("finding_counts")
        if (
            set(review) != _OWNER_REVIEW_KEYS
            or not isinstance(review["reviewer_id"], str)
            or not review["reviewer_id"].strip()
            or not isinstance(review["reviewer_role"], str)
            or not review["reviewer_role"].strip()
            or not isinstance(review["comments"], str)
            or not isinstance(counts, dict)
            or set(counts) != {"critical", "major", "minor"}
            or any(type(value) is not int or value < 0 for value in counts.values())
        ):
            raise CdcOdsImportError("OWNER_REVIEW_SCHEMA_INVALID", str(review.get("gate_id")))
        try:
            reviewed_at = datetime.fromisoformat(str(review["reviewed_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise CdcOdsImportError("OWNER_REVIEW_SCHEMA_INVALID", review["gate_id"]) from exc
        if reviewed_at.utcoffset() is None:
            raise CdcOdsImportError("OWNER_REVIEW_SCHEMA_INVALID", review["gate_id"])
        if counts["critical"] or counts["major"]:
            raise CdcOdsImportError("OWNER_REVIEW_REJECTED", review["gate_id"])
    return reviews


def build_official_cdc_labs_snapshot(
    data_root: Path,
    *,
    raw_revision_id: str,
    approved_golden_cases: Sequence[Mapping[str, Any]],
    owner_reviews: Sequence[Mapping[str, Any]],
    publisher_actor_id: str,
    evidence_files: Sequence[Mapping[str, Any]] = (),
    review_protocol: tuple[str, str] = (
        CDC_LABS_REVIEW_PROTOCOL_ID,
        CDC_LABS_REVIEW_PROTOCOL_VERSION,
    ),
    pre_publish_check: Callable[[Path], tuple[str, str, bytes]] | None = None,
) -> dict[str, Any]:
    """Build and publish an AI-reviewed roster snapshot from a fetched raw revision.

    Every precondition is checked before the first curated write: raw bytes still match
    fetch.json, the application runs from an installed distribution, all four gates carry
    reviews by the reviewer the protocol names without critical or major findings, the sheet
    version equals the attachment version, and at least ten approved golden cases pass.
    """

    from .nhi import _application_build_identity

    data_root = Path(data_root)
    payload, fetch_record, artifact_relative, fetch_relative = _load_official_raw_revision(
        data_root, raw_revision_id
    )
    identity_kind, application_build_hash = _application_build_identity()
    if identity_kind != "distribution":
        raise CdcOdsImportError("APPLICATION_BUILD_IDENTITY_MISSING")
    if not isinstance(publisher_actor_id, str) or not publisher_actor_id.strip():
        raise CdcOdsImportError("PUBLISHER_ACTOR_INVALID")
    review_inputs = _validated_owner_reviews(owner_reviews)
    evidence_inputs = []
    for item in evidence_files:
        name = Path(str(item.get("path", ""))).name
        artifact_id = item.get("artifact_id")
        if (
            not isinstance(artifact_id, str)
            or not artifact_id
            or not _EVIDENCE_NAME_RE.fullmatch(name)
        ):
            raise CdcOdsImportError("EVIDENCE_FILE_INVALID")
        try:
            evidence_inputs.append((artifact_id, name, Path(str(item["path"])).read_bytes()))
        except OSError as exc:
            raise CdcOdsImportError("EVIDENCE_FILE_INVALID", artifact_id) from exc
    if len({name for _, name, _ in evidence_inputs}) != len(evidence_inputs):
        raise CdcOdsImportError("EVIDENCE_FILE_INVALID", "duplicate evidence file name")
    protocol_id, protocol_version, protocol_sha256, reviewer_id, reviewer_role = _review_protocol(
        *review_protocol
    )
    # The review is delegated to the reviewer the protocol names; nobody else may sign it.
    for review in review_inputs:
        if (review["reviewer_id"], review["reviewer_role"]) != (reviewer_id, reviewer_role):
            raise CdcOdsImportError("OWNER_REVIEW_REVIEWER_MISMATCH", review["gate_id"])

    parsed = parse_cdc_labs_ods(payload)
    discovery = fetch_record["discovery"]
    if parsed.sheet_name != f"{discovery['roster_version_raw']}名冊":
        raise CdcOdsImportError("ODS_VERSION_MISMATCH", parsed.sheet_name)
    golden_results = _golden_results(
        parsed, approved_golden_cases, raw_artifact_sha256=sha256_bytes(payload)
    )
    failed = [r["golden_case"]["case_id"] for r in golden_results if r["failure_codes"]]
    if failed:
        raise CdcOdsImportError("GOLDEN_CASE_FAILED", ", ".join(failed))
    if len(golden_results) < _MINIMUM_OFFICIAL_GOLDEN_CASES:
        raise CdcOdsImportError("GOLDEN_CASES_INSUFFICIENT")
    for result in golden_results:
        case = result["golden_case"]
        if (
            case["review_status"] != "approved"
            or case["official_source"] is not True
            or case["evidence_data_root_relative_path"] != artifact_relative
            or case["reviewer_id"] != reviewer_id
        ):
            raise CdcOdsImportError("GOLDEN_CASE_NOT_APPROVED", case["case_id"])
    return _publish_build(
        data_root,
        payload=payload,
        parsed=parsed,
        raw_revision_id=raw_revision_id,
        artifact_relative=artifact_relative,
        fetch_relative=fetch_relative,
        discovery=discovery,
        fetched_at=fetch_record["artifact"]["fetched_at"],
        application_build_hash=application_build_hash,
        golden_results=golden_results,
        review_inputs=review_inputs,
        protocol=(protocol_id, protocol_version, protocol_sha256),
        publisher_actor_id=publisher_actor_id,
        evidence_inputs=evidence_inputs,
        official=True,
        pre_publish_check=pre_publish_check,
    )
