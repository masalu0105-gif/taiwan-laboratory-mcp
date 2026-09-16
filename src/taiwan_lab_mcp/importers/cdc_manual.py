"""CDC specimen collection manual: curated SQLite build (SDD 10.3, ADR 0003).

Owner 2026-09-15 delegated every CDC review to AI (「Ai全程代審 不用特別備注未經人工審核」, OD-04)
and chose B for line breaks inside cells (「我選 B」, OD-15); owner 2026-09-16 added chapter 7
(「手冊第七章也都必須要做」, OD-18). A build stores one table per kind of table the manual prints
(chapter 2 specimen requirements, chapter 7 testing locations, the 7.9 receiving-unit contacts),
each row with its raw cell text, the display text, the PDF row locator, the manual edition and
the row hash. The build fingerprint binds the normalized page layout the rows were read from.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files
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
    _validate_pdf,
    cdc_manual_raw_revision_id,
)
from ..fetch import FetchedArtifact
from ..models import GoldenCaseV1
from ..publish import publish_current_descriptor
from ..util import norm
from .cdc_manual_layout import (
    _HEADERS,
    CDC_MANUAL_LAYOUT_RULES_VERSION,
    CDC_RECEIVING_UNIT_SPEC,
    CDC_SPECIMEN_FIELDS,
    CDC_SPECIMEN_SPEC,
    CDC_TESTING_LOCATION_SPEC,
    CdcSpecimenLayoutResult,
    CdcSpecimenRow,
    CdcTableSpec,
    _read_page,
    _squeeze,
    parse_cdc_receiving_units,
    parse_cdc_revision_entries,
    parse_cdc_specimen_layout,
    parse_cdc_testing_locations,
)
from .cdc_manual_pdf import (
    extract_cdc_manual_layout,
    load_pdfium_qualifier_spec,
    pdfium_qualifier_spec_sha256,
)

# Owner 2026-09-15: 「Ai全程代審 不用特別備注未經人工審核」 covers the specimen manual (OD-04).
CDC_MANUAL_REVIEW_PROTOCOL_ID = "cdc-manual-r1-ai-review"
# Version 2 adds the GitHub Release download bundle and the alias table (owner 2026-09-16).
CDC_MANUAL_REVIEW_PROTOCOL_VERSION = "2"
# Owner 2026-09-15: 「A 開始做疾管署」 (new manual versions switch automatically).
CDC_MANUAL_AUTO_REVIEW_PROTOCOL_ID = "cdc-manual-r1-auto-review"
CDC_MANUAL_AUTO_REVIEW_PROTOCOL_VERSION = "2"
_DELEGATED_REVIEW_PROTOCOLS = frozenset(
    {
        (CDC_MANUAL_REVIEW_PROTOCOL_ID, version)
        for version in ("1", CDC_MANUAL_REVIEW_PROTOCOL_VERSION)
    }
    | {
        (CDC_MANUAL_AUTO_REVIEW_PROTOCOL_ID, version)
        for version in ("1", CDC_MANUAL_AUTO_REVIEW_PROTOCOL_VERSION)
    }
)
_MINIMUM_OFFICIAL_GOLDEN_CASES = 10
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
_OWNER_REVIEW_KEYS = frozenset(
    {"gate_id", "reviewer_id", "reviewer_role", "reviewed_at", "finding_counts", "comments"}
)
# role in fetch.json, stored file name
_RAW_FILES = (("manual", "manual.pdf"), ("revision_table", "revision.pdf"))

CDC_MANUAL_PRIMARY_ARTIFACT_ID = "cdc-manual-pdf"
CDC_MANUAL_REVISION_ARTIFACT_ID = "cdc-manual-revision-pdf"
CDC_MANUAL_SCHEMA_VERSION = "cdc-manual-schema-v1"
CDC_MANUAL_NORMALIZATION_VERSION = "cdc-manual-text-v1"
CDC_MANUAL_FRESHNESS_POLICY_VERSION = "cdc-manual-v1"
CDC_MANUAL_TABLE = "cdc_specimen_requirement"
CDC_MANUAL_SERVING_GATES = ("CDC-R1-SOURCE", "CDC-R1-LAYOUT", "CDC-R1-CONTENT", "PUB-R1-OWNER")
DISPLAY_COLUMNS = tuple(f"{field}_display" for field in CDC_SPECIMEN_FIELDS)
# Every table stores the same locator, edition and row hash beside its own columns.
_LOCATOR_COLUMNS = (
    "row_number",
    "source_row_sha256",
    "pdf_page",
    "printed_page",
    "table_section",
    "row_bbox",
    "manual_version",
    "approved_date_raw",
)
_REQUIRED_LOCATOR_TEXT = frozenset(
    {"source_row_sha256", "table_section", "row_bbox", "manual_version", "approved_date_raw"}
)


@dataclass(frozen=True)
class CdcCuratedTable:
    """One stored table: the layout spec it reads and the column queries search on."""

    spec: CdcTableSpec
    parse: Callable[[dict[str, Any]], CdcSpecimenLayoutResult]
    search_column: str
    search_field: str

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def columns(self) -> tuple[str, ...]:
        return (
            *_LOCATOR_COLUMNS,
            *self.spec.fields,
            *(f"{field}_display" for field in self.spec.fields),
            self.search_column,
        )

    @property
    def required_text(self) -> frozenset[str]:
        return _REQUIRED_LOCATOR_TEXT | {
            self.search_field,
            f"{self.search_field}_display",
            self.search_column,
        }


CDC_MANUAL_TABLES = (
    CdcCuratedTable(CDC_SPECIMEN_SPEC, parse_cdc_specimen_layout, "disease_search", "disease"),
    CdcCuratedTable(
        CDC_TESTING_LOCATION_SPEC, parse_cdc_testing_locations, "disease_search", "disease"
    ),
    CdcCuratedTable(CDC_RECEIVING_UNIT_SPEC, parse_cdc_receiving_units, "unit_search", "unit_name"),
)
CDC_MANUAL_ROW_COLUMNS = CDC_MANUAL_TABLES[0].columns


def _table_sql(table: CdcCuratedTable) -> str:
    # A column order the manual does not print in every section (chapter 2 retention, chapter 7
    # 檢驗期間 and BSL) leaves its raw and display values NULL.
    return "CREATE TABLE {} ({})".format(
        table.name,
        ", ".join(
            f"{column} INTEGER NOT NULL"
            if column in {"row_number", "pdf_page"}
            else f"{column} INTEGER"
            if column == "printed_page"
            else f"{column} TEXT NOT NULL"
            if column in table.required_text
            else f"{column} TEXT"
            for column in table.columns
        ),
    )


def _index_sql(table: CdcCuratedTable) -> str:
    return f"CREATE UNIQUE INDEX {table.name}_row_number ON {table.name} (row_number)"


def _insert_sql(table: CdcCuratedTable) -> str:
    return "INSERT INTO {} ({}) VALUES ({})".format(
        table.name,
        ", ".join(table.columns),
        ", ".join("?" for _ in table.columns),
    )


_SYNTHETIC_MANUAL = b"%PDF-1.7\n% offline synthetic CDC manual fixture\n%%EOF\n"
_SYNTHETIC_REVISION = b"%PDF-1.7\n% offline synthetic CDC manual revision table fixture\n%%EOF\n"


CDC_MANUAL_ALIAS_RULE = "cdc_disease_alias"
CDC_MANUAL_ALIAS_RULE_VERSION = "cdc-disease-alias-v1"


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _alias_bytes() -> bytes:
    resource = files("taiwan_lab_mcp").joinpath("rules", CDC_MANUAL_ALIAS_RULE, "v1.json")
    try:
        return resource.read_bytes()
    except OSError as exc:
        raise CdcManualImportError("ALIAS_RULES_INVALID") from exc


def cdc_disease_alias_sha256() -> str:
    return sha256_bytes(_alias_bytes())


@lru_cache(maxsize=1)
def load_cdc_disease_aliases() -> dict[str, str]:
    """Common names people type mapped to text the manual's own disease names contain (OD-16).

    Both sides are normalized the same way the search column is, so 「COVID-19」 and 「covid 19」
    are one alias. The answer still shows the manual's wording; only the search term changes.
    """

    try:
        document = json.loads(_alias_bytes().decode("utf-8"))
        entries = document["entries"]
        aliases = {norm(entry["alias"]): norm(entry["query"]) for entry in entries}
    except (AttributeError, KeyError, TypeError, UnicodeDecodeError, ValueError) as exc:
        raise CdcManualImportError("ALIAS_RULES_INVALID") from exc
    if (
        document.get("rule_version") != CDC_MANUAL_ALIAS_RULE_VERSION
        or document.get("source_id") != CDC_MANUAL_SOURCE_ID
        or len(aliases) != len(entries)
        or not all(aliases)
        or not all(aliases.values())
    ):
        raise CdcManualImportError("ALIAS_RULES_INVALID")
    return aliases


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


def curated_row(
    table: CdcCuratedTable, row: CdcSpecimenRow, row_number: int, summary: Mapping[str, Any]
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
        table.search_column: norm(display[table.search_field]),
    }


def curated_specimen_row(
    row: CdcSpecimenRow, row_number: int, summary: Mapping[str, Any]
) -> dict[str, Any]:
    """Return one chapter 2 row's stored columns."""

    return curated_row(CDC_MANUAL_TABLES[0], row, row_number, summary)


def parse_cdc_manual_tables(layout: Mapping[str, Any]) -> dict[str, CdcSpecimenLayoutResult]:
    """Read every table a build stores; a manual missing one of them is not built."""

    return {table.name: table.parse(dict(layout)) for table in CDC_MANUAL_TABLES}


def _write_curated_db(db_path: Path, parsed: Mapping[str, CdcSpecimenLayoutResult]) -> None:
    if db_path.exists():
        raise CdcManualImportError("IMMUTABLE_BUILD_EXISTS")
    partial = db_path.with_name(f".{db_path.name}.partial")
    if partial.exists():
        partial.unlink()
    connection = sqlite3.connect(partial)
    succeeded = False
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        for table in CDC_MANUAL_TABLES:
            result = parsed[table.name]
            connection.execute(_table_sql(table))
            connection.executemany(
                _insert_sql(table),
                [
                    tuple(curated[column] for column in table.columns)
                    for curated in (
                        curated_row(table, row, number, result.summary)
                        for number, row in enumerate(result.rows, start=1)
                    )
                ],
            )
            connection.execute(_index_sql(table))
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
                {
                    "fields": list(CDC_SPECIMEN_FIELDS),
                    "rules": CDC_MANUAL_LAYOUT_RULES_VERSION,
                    "tables": {table.name: list(table.spec.fields) for table in CDC_MANUAL_TABLES},
                }
            ),
        },
        "schema": {
            "version": CDC_MANUAL_SCHEMA_VERSION,
            "bundle_sha256": sha256_json(
                {
                    "curated_columns": list(CDC_MANUAL_ROW_COLUMNS),
                    "curated_tables": {
                        table.name: list(table.columns) for table in CDC_MANUAL_TABLES
                    },
                }
            ),
        },
        "normalization": {
            "version": CDC_MANUAL_NORMALIZATION_VERSION,
            "bundle_sha256": sha256_json({"rule": "display-text-NFKC-lower-without-spaces"}),
        },
        "rules": [
            {
                "name": CDC_MANUAL_ALIAS_RULE,
                "version": CDC_MANUAL_ALIAS_RULE_VERSION,
                "bundle_sha256": cdc_disease_alias_sha256(),
            }
        ],
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
    parsed: Mapping[str, CdcSpecimenLayoutResult],
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
    pre_publish_checks: Sequence[Callable[[Path], tuple[str, str, bytes]]] = (),
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
    # Checks run on the finished database before any audit record or pointer refers to it.
    evidence_inputs = [*evidence_inputs, *(check(db_path) for check in pre_publish_checks)]
    audit_prefix = f"{build_prefix}/audit"
    # `counts` describes the source's primary curated table, the same as every other source;
    # `table_counts` covers every table this build stores (chapter 2 and chapter 7).
    table_counts = {name: len(result.rows) for name, result in parsed.items()}
    rows = table_counts[CDC_MANUAL_TABLE]
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
        "table_row_counts": table_counts,
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
            "manual_version": parsed[CDC_MANUAL_TABLE].summary["manual_version"],
            "approved_date_raw": parsed[CDC_MANUAL_TABLE].summary["approved_date_raw"],
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
        "table_counts": table_counts,
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
        "layout_summary": {name: result.summary for name, result in parsed.items()},
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
    parsed = parse_cdc_manual_tables(layout)
    version = parsed[CDC_MANUAL_TABLE].summary["manual_version"]
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


def _review_protocol(protocol_id: str, protocol_version: str) -> tuple[str, str, str, str, str]:
    """Return protocol id, version, SHA-256 and the reviewer id and role it names."""

    if (protocol_id, protocol_version) not in _DELEGATED_REVIEW_PROTOCOLS:
        raise CdcManualImportError("REVIEW_PROTOCOL_INVALID")
    try:
        payload = (
            files("taiwan_lab_mcp")
            .joinpath("review_protocols", protocol_id, f"{protocol_version}.json")
            .read_bytes()
        )
        document = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise CdcManualImportError("REVIEW_PROTOCOL_INVALID") from exc
    if (
        not isinstance(document, dict)
        or document.get("protocol_id") != protocol_id
        or document.get("protocol_version") != protocol_version
        or document.get("source_id") != CDC_MANUAL_SOURCE_ID
        or document.get("status") != "owner_delegated"
        or sorted(document.get("gates", {})) != sorted(CDC_MANUAL_SERVING_GATES)
        or not isinstance(document.get("reviewer_id"), str)
        or not document["reviewer_id"]
        or not isinstance(document.get("reviewer_role"), str)
        or not document["reviewer_role"]
    ):
        raise CdcManualImportError("REVIEW_PROTOCOL_INVALID")
    return (
        protocol_id,
        protocol_version,
        sha256_bytes(payload),
        document["reviewer_id"],
        document["reviewer_role"],
    )


def _validated_owner_reviews(owner_reviews: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    reviews = [dict(review) for review in owner_reviews]
    if [review.get("gate_id") for review in reviews] != list(CDC_MANUAL_SERVING_GATES):
        raise CdcManualImportError("OWNER_REVIEW_GATES_INVALID")
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
            raise CdcManualImportError("OWNER_REVIEW_SCHEMA_INVALID", str(review.get("gate_id")))
        try:
            reviewed_at = datetime.fromisoformat(str(review["reviewed_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise CdcManualImportError("OWNER_REVIEW_SCHEMA_INVALID", review["gate_id"]) from exc
        if reviewed_at.utcoffset() is None:
            raise CdcManualImportError("OWNER_REVIEW_SCHEMA_INVALID", review["gate_id"])
        if counts["critical"] or counts["major"]:
            raise CdcManualImportError("OWNER_REVIEW_REJECTED", review["gate_id"])
    return reviews


def _evidence_inputs(evidence_files: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, bytes]]:
    evidence = []
    for item in evidence_files:
        name = Path(str(item.get("path", ""))).name
        artifact_id = item.get("artifact_id")
        if (
            not isinstance(artifact_id, str)
            or not artifact_id
            or not _EVIDENCE_NAME_RE.fullmatch(name)
        ):
            raise CdcManualImportError("EVIDENCE_FILE_INVALID")
        try:
            evidence.append((artifact_id, name, Path(str(item["path"])).read_bytes()))
        except OSError as exc:
            raise CdcManualImportError("EVIDENCE_FILE_INVALID", artifact_id) from exc
    if len({name for _, name, _ in evidence}) != len(evidence):
        raise CdcManualImportError("EVIDENCE_FILE_INVALID", "duplicate evidence file name")
    return evidence


def _load_official_raw_revision(data_root: Path, raw_revision_id: str) -> dict[str, Any]:
    """Read one fetched manual revision and prove both PDFs still match fetch.json."""

    if not isinstance(raw_revision_id, str) or not _HEX64_RE.fullmatch(raw_revision_id):
        raise CdcManualImportError("RAW_REVISION_INTEGRITY", "raw revision id is invalid")
    revision_dir = PurePosixPath("raw", CDC_MANUAL_SOURCE_ID, raw_revision_id)
    relatives = {role: str(revision_dir / "artifacts" / name) for role, name in _RAW_FILES}
    fetch_relative = str(revision_dir / "fetch.json")
    try:
        fetch_bytes = (data_root / PurePosixPath(fetch_relative)).read_bytes()
        fetch_record = json.loads(fetch_bytes.decode("utf-8"))
        records = {record["role"]: record for record in fetch_record["artifacts"]}
        payloads = {
            role: (data_root / PurePosixPath(relative)).read_bytes()
            for role, relative in relatives.items()
        }
        discovery = fetch_record["discovery"]
        artifacts = {
            role: FetchedArtifact(
                requested_url=records[role]["requested_url"],
                final_url=records[role]["final_url"],
                status_code=records[role]["status_code"],
                payload=payloads[role],
                sha256=sha256_bytes(payloads[role]),
                fetched_at=records[role]["fetched_at"],
                headers=dict(records[role]["headers"]),
                redirect_trace=tuple(records[role]["redirect_trace"]),
            )
            for role in relatives
        }
        recomputed = cdc_manual_raw_revision_id(discovery=discovery, artifacts=artifacts)
        urls = [_document(discovery, role)["pdf_url"] for role in relatives]
    except (KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, AttributeError) as exc:
        raise CdcManualImportError("RAW_REVISION_INTEGRITY", "raw revision is unreadable") from exc
    required_discovery = (
        "provider",
        "dataset_name",
        "landing_url",
        "manual_version_raw",
        "license_name",
        "license_url",
    )
    if (
        canonical_json_bytes(fetch_record) != fetch_bytes
        or fetch_record.get("fetch_record_schema_version") != 1
        or fetch_record.get("source_id") != CDC_MANUAL_SOURCE_ID
        or fetch_record.get("raw_revision_id") != raw_revision_id
        or len(fetch_record["artifacts"]) != len(relatives)
        or set(records) != set(relatives)
        or any(
            records[role].get("data_root_relative_path") != relatives[role]
            or records[role].get("sha256") != sha256_bytes(payloads[role])
            or records[role].get("bytes") != len(payloads[role])
            or records[role].get("media_type_verified") != PDF_MEDIA_TYPE
            or not isinstance(records[role].get("fetched_at"), str)
            for role in relatives
        )
        or recomputed != raw_revision_id
        or any(not isinstance(url, str) or not url for url in urls)
        or any(
            not isinstance(discovery.get(key), str) or not discovery[key]
            for key in required_discovery
        )
    ):
        raise CdcManualImportError(
            "RAW_REVISION_INTEGRITY", "raw revision does not match fetch record"
        )
    return {
        "manual_payload": payloads["manual"],
        "revision_payload": payloads["revision_table"],
        "discovery": discovery,
        "fetched_at": records["manual"]["fetched_at"],
        "artifact_relative": relatives["manual"],
        "revision_relative": relatives["revision_table"],
        "fetch_relative": fetch_relative,
    }


_EXPECTED_FIELDS = frozenset([*CDC_SPECIMEN_FIELDS, *DISPLAY_COLUMNS])


def _golden_failure_codes(
    case: GoldenCaseV1,
    rows: Sequence[CdcSpecimenRow],
    *,
    raw_artifact_sha256: str,
    transform: dict[str, Any],
) -> list[str]:
    codes: list[str] = []
    if case.source_id != CDC_MANUAL_SOURCE_ID:
        codes.append("SOURCE_MISMATCH")
    if (
        case.artifact_id != CDC_MANUAL_PRIMARY_ARTIFACT_ID
        or case.raw_artifact_sha256 != raw_artifact_sha256
    ):
        codes.append("ARTIFACT_MISMATCH")
    if case.transform != transform:
        codes.append("TRANSFORM_MISMATCH")
    if case.expected_status != "ok":
        codes.append("EXPECTED_STATUS_UNSUPPORTED")
    locator = case.source_locator
    if locator.locator_type != "cdc_pdf_row":
        codes.append("LOCATOR_UNSUPPORTED")
    if not case.expected_fields:
        codes.append("EXPECTED_FIELDS_EMPTY")
    codes.extend(
        f"EXPECTED_FIELD_UNSUPPORTED:{field}"
        for field in sorted(set(case.expected_fields) - _EXPECTED_FIELDS)
    )
    disease = case.input.get("disease") if set(case.input) == {"disease"} else None
    if not disease or not norm(disease):
        codes.append("INPUT_UNSUPPORTED")
        return codes
    located = [row for row in rows if row.locator == locator.model_dump()]
    # The case must name a disease that the search tool matches against this row.
    if len(located) != 1 or norm(disease) not in norm(located[0].display_fields()["disease"]):
        codes.append("STATUS_MISMATCH")
        return codes
    row = located[0]
    if case.source_row_sha256 != row.source_row_sha256:
        codes.append("LOCATOR_MISMATCH")
    values = {
        **row.fields(),
        **{f"{name}_display": value for name, value in row.display_fields().items()},
    }
    codes.extend(
        f"FIELD_MISMATCH:{field}"
        for field in sorted(set(case.expected_fields) & _EXPECTED_FIELDS)
        if case.expected_fields[field] != values[field]
    )
    if case.expected_warnings:
        codes.append("WARNINGS_MISMATCH")
    return codes


def evaluate_cdc_manual_golden_cases(
    layout: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    *,
    raw_artifact_sha256: str,
) -> list[dict[str, Any]]:
    """Re-run golden cases against a page layout read from the manual; no writes or approval."""

    parsed = parse_cdc_specimen_layout(dict(layout))
    transform = active_cdc_manual_transform(cdc_layout_sha256(layout))
    validated: list[tuple[dict[str, Any], GoldenCaseV1]] = []
    try:
        for case in cases:
            case_bytes = canonical_json_bytes(dict(case))
            validated.append((json.loads(case_bytes), GoldenCaseV1.model_validate_json(case_bytes)))
    except (TypeError, ValueError) as exc:
        raise CdcManualImportError("GOLDEN_CASE_SCHEMA_INVALID") from exc
    case_ids = [model.case_id for _, model in validated]
    if len(set(case_ids)) != len(case_ids):
        raise CdcManualImportError("GOLDEN_CASE_SCHEMA_INVALID", "duplicate case_id")
    results = []
    for raw_case, model in validated:
        failure_codes = _golden_failure_codes(
            model, parsed.rows, raw_artifact_sha256=raw_artifact_sha256, transform=transform
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


CDC_MANUAL_TAG_CHECK = "cdc-manual-word-tag-text-v1"
_MAX_REPORTED_MISMATCHES = 20


def _column_at(xs: Sequence[float], x: float) -> int | None:
    return next((index for index in range(len(xs) - 1) if xs[index] <= x < xs[index + 1]), None)


def _word_tag_rows(
    layout: Mapping[str, Any], pages: Sequence[int], curated: CdcCuratedTable
) -> list[dict[str, str | None]]:
    """Rebuild one table's rows from the Word TR/TD tags (ADR 0003 decision 5).

    Each TR is one row and each TD's marked-content text is one cell. A TD's column is the space
    between the vertical rules where its characters sit (its marked-content box when it has no
    characters); horizontal rules and character-to-cell grouping are not used. Word lists the
    cells continued from rows above first and this row's own cells last in column order; on a
    page's first row a continued cell with text carries on the previous page's cell.
    """

    wanted = set(pages)
    records: list[dict[str, list[str] | None]] = []
    names: tuple[str | None, ...] = ()
    current: dict[int, list[str]] = {}
    for page in sorted(layout["pages"], key=lambda item: int(item["page_number"])):
        number = int(page["page_number"])
        if number not in wanted:
            continue
        texts: dict[int, list[str]] = {}
        points: dict[int, list[float]] = {}
        for char in page["chars"]:
            mcid = char.get("mcid")
            if mcid is None:
                continue
            texts.setdefault(mcid, []).append(char["text"])
            if char["text"].strip():
                points.setdefault(mcid, []).append((char["x0"] + char["x1"]) / 2)
        boxes: dict[int, list[float]] = {}
        for item in page.get("marked_content", ()):
            boxes.setdefault(item["mcid"], []).append((item["x0"] + item["x1"]) / 2)

        def text_of(child: Sequence[int], texts: dict[int, list[str]] = texts) -> str:
            return _squeeze("".join("".join(texts.get(mcid, ())) for mcid in child))

        def center_of(
            child: Sequence[int],
            points: dict[int, list[float]] = points,
            boxes: dict[int, list[float]] = boxes,
        ) -> float | None:
            found = [x for mcid in child for x in points.get(mcid, ())]
            if not found:
                # Only a cell without visible characters falls back to its marked-content boxes.
                found = [x for mcid in child for x in boxes.get(mcid, ())]
            return sum(found) / len(found) if found else None

        table = _read_page(page)
        if table is None:
            raise CdcManualImportError("LAYOUT_TAG_TEXT_MISMATCH", f"page {number} has no table")

        def column_of(
            child: Sequence[int], xs: Sequence[float] = table.xs, center_of: Any = center_of
        ) -> int | None:
            center = center_of(child)
            return None if center is None else _column_at(xs, center)

        rows = [row for row in page.get("table_rows") or () if any(c is not None for c in row)]
        header_rows = [
            index
            for index, row in enumerate(rows)
            if any(child is not None and text_of(child) == curated.spec.anchor for child in row)
        ]
        if header_rows:
            header = rows[header_rows[-1]]
            header_names: list[str | None] = [None] * (len(table.xs) - 1)
            for child in header:
                column = None if child is None else column_of(child)
                if column is not None:
                    header_names[column] = _HEADERS.get(text_of(child))
            if len(header) != len(header_names) or None in header_names:
                raise CdcManualImportError("LAYOUT_TAG_TEXT_MISMATCH", f"page {number} header")
            if len(header_names) != len(names):
                current = {}
            names = tuple(header_names)
            rows = rows[header_rows[-1] + 1 :]
        if not names:
            raise CdcManualImportError("LAYOUT_TAG_TEXT_MISMATCH", f"page {number} has no header")
        for position, row in enumerate(rows):
            if len(row) != len(names):
                raise CdcManualImportError("LAYOUT_TAG_TEXT_MISMATCH", f"page {number} row width")
            columns = [None if child is None else column_of(child) for child in row]
            boundary = len(row)
            last = None
            for index in range(len(row) - 1, -1, -1):
                if row[index] is None:
                    break
                column = columns[index]
                if column is not None:
                    if last is not None and column >= last:
                        break
                    last = column
                boundary = index
            for index in range(boundary):
                child = row[index]
                if child is None or not text_of(child):
                    continue
                column = columns[index]
                if position > 0 or column is None or column not in current:
                    raise CdcManualImportError(
                        "LAYOUT_TAG_TEXT_MISMATCH", f"page {number} continued cell"
                    )
                current[column].append(text_of(child))
            # An own cell without characters or position takes the column left between its
            # neighbours; anything else cannot be placed safely.
            gap: list[Sequence[int]] = []
            previous = -1
            for index in [*range(boundary, len(row)), None]:
                column = len(names) if index is None else columns[index]
                if column is None:
                    gap.append(row[index])  # type: ignore[index]
                    continue
                if gap:
                    between = range(previous + 1, column)
                    if len(between) != len(gap):
                        raise CdcManualImportError(
                            "LAYOUT_TAG_TEXT_MISMATCH", f"page {number} empty cell"
                        )
                    for gap_column, child in zip(between, gap):
                        current[gap_column] = [text_of(child)]
                    gap = []
                if index is not None:
                    current[column] = [text_of(row[index])]  # type: ignore[arg-type]
                previous = column
            records.append({name: current.get(column) for column, name in enumerate(names) if name})
    return [
        {
            field: None if record.get(field) is None else "".join(record[field] or ())
            for field in curated.spec.fields
        }
        for record in records
    ]


def verify_cdc_manual_rows_against_tags(
    layout: Mapping[str, Any], db_path: Path
) -> tuple[str, str, bytes]:
    """Compare every stored row's raw cells with the Word tag reading; raise on any difference."""

    connection = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        stored = {
            table.name: [
                dict(row)
                for row in connection.execute(f"SELECT * FROM {table.name} ORDER BY row_number")
            ]
            for table in CDC_MANUAL_TABLES
        }
    finally:
        connection.close()
    mismatches: list[dict[str, Any]] = []
    compared: dict[str, dict[str, int]] = {}
    for table in CDC_MANUAL_TABLES:
        rows = stored[table.name]
        tagged = _word_tag_rows(layout, sorted({row["pdf_page"] for row in rows}), table)
        compared[table.name] = {
            "rows_compared": len(rows),
            "cells_compared": len(rows) * len(table.spec.fields),
        }
        if len(tagged) != len(rows):
            mismatches.append(
                {
                    "table": table.name,
                    "row_number": None,
                    "field": "rows",
                    "stored": len(rows),
                    "tags": len(tagged),
                }
            )
        for row, record in zip(rows, tagged):
            for field in table.spec.fields:
                value = None if row[field] is None else _squeeze(row[field])
                if value != record[field]:
                    mismatches.append(
                        {
                            "table": table.name,
                            "row_number": row["row_number"],
                            "pdf_page": row["pdf_page"],
                            "field": field,
                            "stored": value,
                            "tags": record[field],
                        }
                    )
    if mismatches:
        raise CdcManualImportError(
            "LAYOUT_TAG_TEXT_MISMATCH",
            json.dumps(mismatches[:_MAX_REPORTED_MISMATCHES], ensure_ascii=False),
        )
    report = {
        "check": CDC_MANUAL_TAG_CHECK,
        "rows_compared": sum(item["rows_compared"] for item in compared.values()),
        "cells_compared": sum(item["cells_compared"] for item in compared.values()),
        "tables": compared,
        "mismatches": [],
    }
    return "cdc-manual-tag-check", "word-tag-check.json", canonical_json_bytes(report)


CDC_MANUAL_REVISION_CHANGES = "cdc-manual-revision-change-list-v1"


def cdc_manual_revision_change_list(
    revision_payload: bytes, *, approved_date_raw: str | None
) -> tuple[str, str, bytes]:
    """Read the revision table's change list as build evidence (OD-18).

    The list says which printed pages this edition changed and why, so the content review can
    compare it with the rows that actually differ. The 修正規定 and 現行規定 columns reprint the
    manual's own tables and are not copied here.
    """

    layout = extract_cdc_manual_layout(revision_payload)
    parsed = parse_cdc_revision_entries(layout)
    report = {
        "check": CDC_MANUAL_REVISION_CHANGES,
        "rules_version": CDC_MANUAL_LAYOUT_RULES_VERSION,
        # The manual prints 核准日期 and the revision table 製表日期; both are kept as printed.
        "approved_date_raw": approved_date_raw,
        "compiled_date_raw": parsed.summary["compiled_date_raw"],
        "revision_layout_sha256": cdc_layout_sha256(layout),
        "revision_pages": parsed.summary["table_pages"],
        "entries": [
            {
                **row.fields(),
                "pdf_page": row.locator["pdf_page"],
                "continues_on_pages": list(row.continues_on_pages),
            }
            for row in parsed.rows
        ],
    }
    return "cdc-manual-revision-changes", "revision-changes.json", canonical_json_bytes(report)


def build_official_cdc_manual_snapshot(
    data_root: Path,
    *,
    raw_revision_id: str,
    approved_golden_cases: Sequence[Mapping[str, Any]],
    owner_reviews: Sequence[Mapping[str, Any]],
    publisher_actor_id: str,
    evidence_files: Sequence[Mapping[str, Any]] = (),
    review_protocol: tuple[str, str] = (
        CDC_MANUAL_REVIEW_PROTOCOL_ID,
        CDC_MANUAL_REVIEW_PROTOCOL_VERSION,
    ),
    pre_publish_check: Callable[[Path], tuple[str, str, bytes]] | None = None,
) -> dict[str, Any]:
    """Build and publish an AI-reviewed manual snapshot from a fetched raw revision.

    Every precondition is checked before the first curated write: both PDFs still match
    fetch.json, the application runs from an installed distribution, all four gates carry
    reviews by the reviewer the protocol names without critical or major findings, every table
    page prints the attachment edition, and at least ten approved golden cases pass.
    """

    from .nhi import _application_build_identity

    data_root = Path(data_root)
    raw = _load_official_raw_revision(data_root, raw_revision_id)
    _validate_pdf(raw["manual_payload"])
    _validate_pdf(raw["revision_payload"])
    identity_kind, application_build_hash = _application_build_identity()
    if identity_kind != "distribution":
        raise CdcManualImportError("APPLICATION_BUILD_IDENTITY_MISSING")
    if not isinstance(publisher_actor_id, str) or not publisher_actor_id.strip():
        raise CdcManualImportError("PUBLISHER_ACTOR_INVALID")
    review_inputs = _validated_owner_reviews(owner_reviews)
    evidence_inputs = list(_evidence_inputs(evidence_files))
    protocol_id, protocol_version, protocol_sha256, reviewer_id, reviewer_role = _review_protocol(
        *review_protocol
    )
    # The review is delegated to the reviewer the protocol names; nobody else may sign it.
    for review in review_inputs:
        if (review["reviewer_id"], review["reviewer_role"]) != (reviewer_id, reviewer_role):
            raise CdcManualImportError("OWNER_REVIEW_REVIEWER_MISMATCH", review["gate_id"])

    layout = extract_cdc_manual_layout(raw["manual_payload"])
    parsed = parse_cdc_manual_tables(layout)
    summary = parsed[CDC_MANUAL_TABLE].summary
    discovery = raw["discovery"]
    if summary["manual_version"] != discovery["manual_version_raw"]:
        raise CdcManualImportError("MANUAL_VERSION_MISMATCH", summary["manual_version"])
    # The revision table is read too, so the review sees what this edition says it changed.
    evidence_inputs.append(
        cdc_manual_revision_change_list(
            raw["revision_payload"], approved_date_raw=summary["approved_date_raw"]
        )
    )
    raw_digest = sha256_bytes(raw["manual_payload"])
    golden_results = evaluate_cdc_manual_golden_cases(
        layout, approved_golden_cases, raw_artifact_sha256=raw_digest
    )
    failed = [r["golden_case"]["case_id"] for r in golden_results if r["failure_codes"]]
    if failed:
        raise CdcManualImportError("GOLDEN_CASE_FAILED", ", ".join(failed))
    if len(golden_results) < _MINIMUM_OFFICIAL_GOLDEN_CASES:
        raise CdcManualImportError("GOLDEN_CASES_INSUFFICIENT")
    for result in golden_results:
        case = result["golden_case"]
        if (
            case["review_status"] != "approved"
            or case["official_source"] is not True
            or case["evidence_data_root_relative_path"] != raw["artifact_relative"]
            or case["reviewer_id"] != reviewer_id
        ):
            raise CdcManualImportError("GOLDEN_CASE_NOT_APPROVED", case["case_id"])
    return _publish_build(
        data_root,
        manual_payload=raw["manual_payload"],
        revision_payload=raw["revision_payload"],
        parsed=parsed,
        layout_sha256=cdc_layout_sha256(layout),
        raw_revision_id=raw_revision_id,
        artifact_relative=raw["artifact_relative"],
        revision_relative=raw["revision_relative"],
        fetch_relative=raw["fetch_relative"],
        discovery=discovery,
        fetched_at=raw["fetched_at"],
        application_build_hash=application_build_hash,
        golden_results=golden_results,
        review_inputs=review_inputs,
        protocol=(protocol_id, protocol_version, protocol_sha256),
        publisher_actor_id=publisher_actor_id,
        evidence_inputs=evidence_inputs,
        official=True,
        pre_publish_checks=[
            lambda db_path: verify_cdc_manual_rows_against_tags(layout, db_path),
            *([pre_publish_check] if pre_publish_check is not None else []),
        ],
    )
