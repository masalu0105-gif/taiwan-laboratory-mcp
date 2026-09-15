"""CDC specimen collection manual chapter 2: curated SQLite build (SDD 10.3, ADR 0003).

Owner 2026-09-15 delegated every CDC review to AI (「Ai全程代審 不用特別備注未經人工審核」, OD-04)
and chose B for line breaks inside cells (「我選 B」, OD-15). A build keeps every chapter 2 row
with its raw cell text, the display text, the PDF row locator, the manual edition and the row
hash. The build fingerprint binds the normalized page layout the rows were read from.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from ..audit import _sha256_file, compute_review_subject_digest
from ..canonical import canonical_json_bytes, sha256_bytes, sha256_json
from ..cdc_manual_source import (
    CDC_MANUAL_DATASET_NAME,
    CDC_MANUAL_LANDING_URL,
    CDC_MANUAL_SOURCE_ID,
    PDF_MEDIA_TYPE,
    CdcManualImportError,
    cdc_manual_raw_revision_id,
)
from ..publish import publish_current_descriptor
from ..util import norm
from .cdc_manual_layout import (
    CDC_MANUAL_LAYOUT_RULES_VERSION,
    CDC_SPECIMEN_FIELDS,
    CdcSpecimenLayoutResult,
    CdcSpecimenRow,
    parse_cdc_specimen_layout,
)
from .cdc_manual_pdf import load_pdfium_qualifier_spec, pdfium_qualifier_spec_sha256

CDC_MANUAL_PRIMARY_ARTIFACT_ID = "cdc-manual-pdf"
CDC_MANUAL_REVISION_ARTIFACT_ID = "cdc-manual-revision-pdf"
CDC_MANUAL_SCHEMA_VERSION = "cdc-manual-schema-v1"
CDC_MANUAL_NORMALIZATION_VERSION = "cdc-manual-text-v1"
CDC_MANUAL_FRESHNESS_POLICY_VERSION = "cdc-manual-v1"
CDC_MANUAL_TABLE = "cdc_specimen_requirement"
CDC_MANUAL_SERVING_GATES = ("CDC-R1-SOURCE", "CDC-R1-LAYOUT", "CDC-R1-CONTENT", "PUB-R1-OWNER")
DISPLAY_COLUMNS = tuple(f"{field}_display" for field in CDC_SPECIMEN_FIELDS)
CDC_MANUAL_ROW_COLUMNS = (
    "row_number",
    "source_row_sha256",
    "pdf_page",
    "printed_page",
    "table_section",
    "row_bbox",
    "manual_version",
    "approved_date_raw",
    *CDC_SPECIMEN_FIELDS,
    *DISPLAY_COLUMNS,
    "disease_search",
)
_REQUIRED_TEXT = frozenset(
    {
        "source_row_sha256",
        "table_section",
        "row_bbox",
        "manual_version",
        "approved_date_raw",
        "disease",
        "disease_display",
        "disease_search",
    }
)
# Seven-column tables have no retention column, so the raw and display values may be NULL.
_TABLE_SQL = "CREATE TABLE {} ({})".format(
    CDC_MANUAL_TABLE,
    ", ".join(
        f"{column} INTEGER NOT NULL"
        if column in {"row_number", "pdf_page"}
        else f"{column} INTEGER"
        if column == "printed_page"
        else f"{column} TEXT NOT NULL"
        if column in _REQUIRED_TEXT
        else f"{column} TEXT"
        for column in CDC_MANUAL_ROW_COLUMNS
    ),
)
_INDEX_SQL = (f"CREATE UNIQUE INDEX cdc_specimen_row_number ON {CDC_MANUAL_TABLE} (row_number)",)
_INSERT_SQL = "INSERT INTO {} ({}) VALUES ({})".format(
    CDC_MANUAL_TABLE,
    ", ".join(CDC_MANUAL_ROW_COLUMNS),
    ", ".join("?" for _ in CDC_MANUAL_ROW_COLUMNS),
)
_SYNTHETIC_MANUAL = b"%PDF-1.7\n% offline synthetic CDC manual fixture\n%%EOF\n"
_SYNTHETIC_REVISION = b"%PDF-1.7\n% offline synthetic CDC manual revision table fixture\n%%EOF\n"


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _thousandths(value: Any) -> Any:
    if isinstance(value, float):
        return round(value * 1000)
    if isinstance(value, dict):
        return {key: _thousandths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_thousandths(item) for item in value]
    return value


def cdc_layout_sha256(layout: Mapping[str, Any]) -> str:
    """SHA-256 of a CdcLayoutV1 with every coordinate as whole thousandths of a point.

    Canonical JSON has no floats; the extractor keeps three decimals, so nothing is lost.
    """

    return sha256_bytes(canonical_json_bytes(_thousandths(dict(layout))))


def curated_specimen_row(
    row: CdcSpecimenRow, row_number: int, summary: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the stored columns: raw text, display text, locator, edition and search key."""

    display = row.display_fields()
    return {
        "row_number": row_number,
        "source_row_sha256": row.source_row_sha256,
        "pdf_page": row.locator["pdf_page"],
        "printed_page": row.locator["printed_page"],
        "table_section": row.locator["table_section"],
        "row_bbox": canonical_json_bytes(row.locator["row_bbox"]).decode("utf-8"),
        "manual_version": summary["manual_version"],
        "approved_date_raw": summary["approved_date_raw"],
        **row.fields(),
        **{f"{name}_display": value for name, value in display.items()},
        "disease_search": norm(display["disease"]),
    }


def _write_curated_db(db_path: Path, parsed: CdcSpecimenLayoutResult) -> None:
    if db_path.exists():
        raise CdcManualImportError("IMMUTABLE_BUILD_EXISTS")
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
                tuple(curated[column] for column in CDC_MANUAL_ROW_COLUMNS)
                for curated in (
                    curated_specimen_row(row, number, parsed.summary)
                    for number, row in enumerate(parsed.rows, start=1)
                )
            ],
        )
        for statement in _INDEX_SQL:
            connection.execute(statement)
        connection.commit()
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise CdcManualImportError("SQLITE_INTEGRITY_FAILURE")
        succeeded = True
    except sqlite3.IntegrityError as exc:
        raise CdcManualImportError("CURATED_ROW_INVALID") from exc
    finally:
        connection.close()
        if not succeeded and partial.exists():
            partial.unlink()
    os.replace(partial, db_path)


def active_cdc_manual_transform(layout_sha256: str | None) -> dict[str, Any]:
    """Return the reading rules, schema, normalization and PDFium identity a build binds to."""

    spec = load_pdfium_qualifier_spec()
    return {
        "parser": {
            "version": CDC_MANUAL_LAYOUT_RULES_VERSION,
            "bundle_sha256": sha256_json(
                {"fields": list(CDC_SPECIMEN_FIELDS), "rules": CDC_MANUAL_LAYOUT_RULES_VERSION}
            ),
        },
        "schema": {
            "version": CDC_MANUAL_SCHEMA_VERSION,
            "bundle_sha256": sha256_json({"curated_columns": list(CDC_MANUAL_ROW_COLUMNS)}),
        },
        "normalization": {
            "version": CDC_MANUAL_NORMALIZATION_VERSION,
            "bundle_sha256": sha256_json({"rule": "display-text-NFKC-lower-without-spaces"}),
        },
        "rules": [],
        "qualifier": {
            "name": spec["spec_id"],
            "version": spec["package_version"],
            "spec_sha256": pdfium_qualifier_spec_sha256(),
            "extractor_output_sha256": layout_sha256,
        },
    }


def _write_audit_json(path: Path, value: Mapping[str, Any]) -> str:
    payload = canonical_json_bytes(dict(value))
    if path.exists():
        if path.read_bytes() != payload:
            raise CdcManualImportError("IMMUTABLE_AUDIT_CONFLICT")
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
    current_path = data_root / "manifests" / "current" / f"{CDC_MANUAL_SOURCE_ID}.json"
    if not current_path.is_file():
        return 0, None
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
        return int(current["generation"]), current["serving_snapshot_id"]
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise CdcManualImportError("CURRENT_POINTER_INTEGRITY") from exc


def _document(discovery: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    matches = [document for document in discovery["documents"] if document["role"] == role]
    if len(matches) != 1:
        raise CdcManualImportError("RAW_REVISION_INTEGRITY", f"{role} document")
    return matches[0]


def _publish_build(
    data_root: Path,
    *,
    manual_payload: bytes,
    revision_payload: bytes,
    parsed: CdcSpecimenLayoutResult,
    layout_sha256: str,
    raw_revision_id: str,
    artifact_relative: str,
    revision_relative: str,
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

    raw_digest = sha256_bytes(manual_payload)
    manual_document = _document(discovery, "manual")
    transform = active_cdc_manual_transform(layout_sha256)
    build_fingerprint = {
        "fingerprint_schema": "curated-build-v1",
        "source_id": CDC_MANUAL_SOURCE_ID,
        "raw_revision_id": raw_revision_id,
        "application_build_sha256": application_build_hash,
        **transform,
    }
    build_hash = sha256_json(build_fingerprint)
    build_id = f"{CDC_MANUAL_SOURCE_ID}-build-{build_hash}"
    build_prefix = f"curated/{CDC_MANUAL_SOURCE_ID}/{build_id}"
    build_dir = data_root / PurePosixPath(build_prefix)
    if build_dir.exists():
        raise CdcManualImportError("IMMUTABLE_BUILD_EXISTS")
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
        {"artifact_id": CDC_MANUAL_PRIMARY_ARTIFACT_ID, "role": "primary", "sha256": raw_digest}
    ]
    synthetic_ci_status = "not_run" if official else "passed"
    validation = {
        "validation_schema_version": 1,
        "source_id": CDC_MANUAL_SOURCE_ID,
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
        "source_id": CDC_MANUAL_SOURCE_ID,
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
            "pre-review candidate for an AI-reviewed official CDC manual build"
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
        "source_id": CDC_MANUAL_SOURCE_ID,
        "state": "approved",
        "source": {
            "provider": discovery["provider"],
            "dataset_name": discovery["dataset_name"],
            "landing_url": discovery["landing_url"],
            "resource_url": manual_document["pdf_url"],
            "attachment_label": manual_document["attachment_label"],
            "license_name": discovery["license_name"],
            "license_url": discovery["license_url"],
            "attribution": f"資料提供機關：{discovery['provider']}",
        },
        "official_version": {
            "label": discovery["manual_version_raw"],
            "modified_at_raw": None,
            "modified_at_precision": "unknown",
            "timezone_known": False,
        },
        "manual_edition": {
            "manual_version": parsed.summary["manual_version"],
            "approved_date_raw": parsed.summary["approved_date_raw"],
        },
        "fetched_at": fetched_at,
        "artifacts": [
            {
                "artifact_id": CDC_MANUAL_PRIMARY_ARTIFACT_ID,
                "role": "primary",
                "resource_url": manual_document["pdf_url"],
                "storage_scope": "data_root",
                "data_root_relative_path": artifact_relative,
                "local_artifact_available": True,
                "media_type_verified": PDF_MEDIA_TYPE,
                "bytes": len(manual_payload),
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
            "required_gates": list(CDC_MANUAL_SERVING_GATES),
            "completed_gates": list(CDC_MANUAL_SERVING_GATES),
            "capability_reviews": [],
        },
        "layout_summary": parsed.summary,
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
            "artifact_id": CDC_MANUAL_PRIMARY_ARTIFACT_ID,
            "path": artifact_relative,
            "locator": {"kind": "source_artifact"},
            "sha256": raw_digest,
        },
        {
            "artifact_id": CDC_MANUAL_REVISION_ARTIFACT_ID,
            "path": revision_relative,
            "locator": {"kind": "source_artifact"},
            "sha256": sha256_bytes(revision_payload),
        },
    ]
    if fetch_relative is not None:
        fetch_digest = _sha256_file(data_root / PurePosixPath(fetch_relative))
        manifest["discovery"] = {"data_root_relative_path": fetch_relative, "sha256": fetch_digest}
        evidence_refs.append(
            {
                "artifact_id": "cdc-manual-fetch-record",
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
                "artifact_id": "cdc-manual-curated-db",
                "path": db_relative,
                "locator": {"kind": "sqlite_snapshot"},
                "sha256": db_digest,
            },
            {
                "artifact_id": "cdc-manual-validation",
                "path": validation_relative,
                "locator": {"kind": "validation_report"},
                "sha256": validation_digest,
            },
            {
                "artifact_id": "cdc-manual-qualification-candidate",
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
            "source_id": CDC_MANUAL_SOURCE_ID,
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
        "source_id": CDC_MANUAL_SOURCE_ID,
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
    check_id = f"{CDC_MANUAL_SOURCE_ID}-check-{build_hash}-g{generation}"
    check_relative = f"checks/{CDC_MANUAL_SOURCE_ID}/{check_id}.json"
    operational = {
        "latest_seen_version": discovery["manual_version_raw"],
        "latest_seen_artifact_sha256": raw_digest,
        "latest_candidate_id": None,
        "latest_candidate_status": "none",
        "check_result": "success",
        "failed_stage": None,
        "error_code": None,
        "stale": False,
        "stale_reason_codes": [],
        "freshness_policy_version": CDC_MANUAL_FRESHNESS_POLICY_VERSION,
        "content_age_status": "unknown",
        "content_age_evidence": None,
    }
    check = {
        "check_schema_version": 1,
        "check_id": check_id,
        "source_id": CDC_MANUAL_SOURCE_ID,
        "generation": generation,
        "serving_snapshot_id": build_id,
        "serving_curated_build_id": build_id,
        "checked_at": checked_at,
        **operational,
    }
    check_digest = _write_audit_json(data_root / PurePosixPath(check_relative), check)
    descriptor = {
        "descriptor_schema_version": 1,
        "source_id": CDC_MANUAL_SOURCE_ID,
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


def _write_raw(data_root: Path, relative: str, payload: bytes) -> None:
    path = data_root / PurePosixPath(relative)
    if path.exists():
        if path.read_bytes() != payload:
            raise CdcManualImportError("IMMUTABLE_RAW_CONFLICT")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def build_cdc_manual_snapshot(
    layout: Mapping[str, Any],
    data_root: Path,
    *,
    manual_payload: bytes = _SYNTHETIC_MANUAL,
    revision_payload: bytes = _SYNTHETIC_REVISION,
) -> dict[str, Any]:
    """Build and serve a synthetic manual snapshot from a caller-supplied page layout.

    Offline and test-only: the layout does not come from the PDF bytes, and the reviews are
    offline-test-builder fixtures, never official source qualification.
    """

    from ..cdc_source import CDC_LICENSE_NAME, CDC_LICENSE_URL, CDC_PROVIDER
    from ..fetch import FetchedArtifact
    from .nhi import _application_build_identity

    data_root = Path(data_root)
    parsed = parse_cdc_specimen_layout(dict(layout))
    version = parsed.summary["manual_version"]
    fetched_at = _utc_now_text()
    documents = [
        (
            "manual",
            f"衛生福利部疾病管制署傳染病檢體採檢手冊-{version}版.pdf",
            "https://www.cdc.gov.tw/Uploads/offline-synthetic-manual.pdf",
            manual_payload,
        ),
        (
            "revision_table",
            f"傳染病檢體採檢手冊修訂對照表-{version}.pdf",
            "https://www.cdc.gov.tw/Uploads/offline-synthetic-revision.pdf",
            revision_payload,
        ),
    ]
    discovery = {
        "provider": CDC_PROVIDER,
        "dataset_name": CDC_MANUAL_DATASET_NAME,
        "landing_url": CDC_MANUAL_LANDING_URL,
        "manual_version_raw": version,
        "documents": [
            {"role": role, "attachment_label": label, "pdf_url": url}
            for role, label, url, _ in documents
        ],
        "license_name": CDC_LICENSE_NAME,
        "license_url": CDC_LICENSE_URL,
    }
    artifacts = {
        role: FetchedArtifact(
            requested_url=url,
            final_url=url,
            status_code=200,
            payload=payload,
            sha256=sha256_bytes(payload),
            fetched_at=fetched_at,
            headers={},
            redirect_trace=(),
        )
        for role, _, url, payload in documents
    }
    raw_revision_id = cdc_manual_raw_revision_id(discovery=discovery, artifacts=artifacts)
    revision_dir = f"raw/{CDC_MANUAL_SOURCE_ID}/{raw_revision_id}/artifacts"
    artifact_relative = f"{revision_dir}/manual.pdf"
    revision_relative = f"{revision_dir}/revision.pdf"
    _write_raw(data_root, artifact_relative, manual_payload)
    _write_raw(data_root, revision_relative, revision_payload)
    review_inputs = [
        {
            "gate_id": gate_id,
            "reviewer_id": "offline-test-builder",
            "reviewer_role": "test_fixture_reviewer",
            "reviewed_at": fetched_at,
            "finding_counts": {"critical": 0, "major": 0, "minor": 0},
            "comments": "Synthetic fixture review only; not official source qualification.",
        }
        for gate_id in CDC_MANUAL_SERVING_GATES
    ]
    return _publish_build(
        data_root,
        manual_payload=manual_payload,
        revision_payload=revision_payload,
        parsed=parsed,
        layout_sha256=cdc_layout_sha256(layout),
        raw_revision_id=raw_revision_id,
        artifact_relative=artifact_relative,
        revision_relative=revision_relative,
        fetch_relative=None,
        discovery=discovery,
        fetched_at=fetched_at,
        application_build_hash=_application_build_identity()[1],
        golden_results=[],
        review_inputs=review_inputs,
        protocol=(
            "cdc-manual-r1-synthetic-fixture",
            "1",
            sha256_json(
                {"protocol_id": "cdc-manual-r1-synthetic-fixture", "protocol_version": "1"}
            ),
        ),
        publisher_actor_id="offline-test-builder",
        evidence_inputs=(),
        official=False,
    )
