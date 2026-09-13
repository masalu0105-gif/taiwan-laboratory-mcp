from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, distribution
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

from ..audit import compute_review_subject_digest
from ..canonical import canonical_json_bytes, sha256_bytes, sha256_json
from ..models import NHIRecord
from ..nhi_source import nhi_discovery_metadata_sha256, nhi_raw_revision_id
from ..publish import publish_current_descriptor
from ..rules.nhi import parse_alias_bundle, parse_scope_bundle
from ..util import search_normalize

NHI_COLUMNS = (
    "診療項目代碼",
    "健保支付點數",
    "生效起日",
    "生效迄日",
    "英文項目名稱",
    "中文項目名稱",
    "備註",
)
_DATE_RE = re.compile(r"^[0-9]{8}$")
_POINTS_RE = re.compile(r"^[0-9]+$")


class NHIImportError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}{(': ' + detail) if detail else ''}")


@dataclass(frozen=True)
class NHIParsedRow:
    source_row_number: int
    source_row_sha256: str
    code_raw: str
    code_normalized: str
    points_raw: str
    points: int
    effective_start_raw: str
    effective_start: str
    effective_end_raw: str
    effective_end: str
    possible_open_end_sentinel: bool
    name_en_raw: str
    name_zh_raw: str
    note_raw: str

    def to_record(
        self,
        scope_status: str = "review_pending",
        matched_by: list[str] | None = None,
    ) -> NHIRecord:
        return NHIRecord(
            matched_by=matched_by or ["code"],
            code_raw=self.code_raw,
            code_normalized=self.code_normalized,
            points_raw=self.points_raw,
            points=self.points,
            effective_start_raw=self.effective_start_raw,
            effective_start=self.effective_start,
            effective_end_raw=self.effective_end_raw,
            effective_end=self.effective_end,
            possible_open_end_sentinel=self.possible_open_end_sentinel,
            name_zh_raw=self.name_zh_raw or None,
            name_zh_search=search_normalize(self.name_zh_raw) or None,
            name_en_raw=self.name_en_raw or None,
            name_en_search=search_normalize(self.name_en_raw) or None,
            note_raw=self.note_raw or None,
            note_search=search_normalize(self.note_raw) or None,
            scope_status=scope_status,
            scope_rule_version="nhi-lab-scope-v1",
            scope_basis_locator=None,
        )


@dataclass(frozen=True)
class NHIParseResult:
    rows: tuple[NHIParsedRow, ...]
    warnings: tuple[str, ...]


def _parse_date(raw: str, field: str) -> str:
    if not _DATE_RE.fullmatch(raw):
        raise NHIImportError("DATE_INVALID", f"{field} must be YYYYMMDD")
    try:
        return datetime.strptime(raw, "%Y%m%d").date().isoformat()
    except ValueError as exc:
        raise NHIImportError("DATE_INVALID", f"{field} is not a Gregorian date") from exc


def parse_nhi_csv(payload: bytes) -> NHIParseResult:
    if not isinstance(payload, bytes) or not payload:
        raise NHIImportError("EMPTY_INPUT")
    if b"\x00" in payload:
        raise NHIImportError("NUL_BYTE")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise NHIImportError("DECODE_ERROR") from exc
    if "\ufffd" in text:
        raise NHIImportError("DECODE_REPLACEMENT_CHARACTER")

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise NHIImportError("ZERO_ROWS") from exc
    except csv.Error as exc:
        raise NHIImportError("CSV_PARSE_ERROR") from exc
    if header != list(NHI_COLUMNS):
        if len(header) != len(set(header)):
            raise NHIImportError("SCHEMA_DUPLICATE_COLUMN")
        raise NHIImportError("SCHEMA_HEADER_MISMATCH")

    rows: list[NHIParsedRow] = []
    seen_codes: set[str] = set()
    try:
        for source_row_number, values in enumerate(reader, start=2):
            if not values or all(value == "" for value in values):
                raise NHIImportError("MALFORMED_RECORD", f"source row {source_row_number}")
            if values == list(NHI_COLUMNS):
                raise NHIImportError("SCHEMA_DUPLICATE_HEADER", f"source row {source_row_number}")
            if len(values) != len(NHI_COLUMNS):
                raise NHIImportError("ROW_WIDTH_MISMATCH", f"source row {source_row_number}")
            code_raw, points_raw, start_raw, end_raw, name_en, name_zh, note = values
            code_normalized = search_normalize(code_raw)
            if not code_raw.strip() or not code_normalized or not name_zh.strip():
                raise NHIImportError("REQUIRED_VALUE_MISSING", f"source row {source_row_number}")
            if code_normalized in seen_codes:
                raise NHIImportError("DUPLICATE_LOGICAL_KEY", code_raw.strip())
            seen_codes.add(code_normalized)
            if not _POINTS_RE.fullmatch(points_raw):
                raise NHIImportError("POINTS_INVALID", f"source row {source_row_number}")
            start = _parse_date(start_raw, "effective_start")
            end = _parse_date(end_raw, "effective_end")
            if start > end:
                raise NHIImportError("DATE_RANGE_INVALID", f"source row {source_row_number}")
            try:
                points = int(points_raw, 10)
            except ValueError as exc:
                raise NHIImportError("POINTS_INVALID", f"source row {source_row_number}") from exc
            raw_values = [code_raw, points_raw, start_raw, end_raw, name_en, name_zh, note]
            rows.append(
                NHIParsedRow(
                    source_row_number=source_row_number,
                    source_row_sha256=sha256_bytes(canonical_json_bytes(raw_values)),
                    code_raw=code_raw,
                    code_normalized=code_normalized,
                    points_raw=points_raw,
                    points=points,
                    effective_start_raw=start_raw,
                    effective_start=start,
                    effective_end_raw=end_raw,
                    effective_end=end,
                    possible_open_end_sentinel=end_raw == "29101231",
                    name_en_raw=name_en,
                    name_zh_raw=name_zh,
                    note_raw=note,
                )
            )
    except csv.Error as exc:
        raise NHIImportError("CSV_PARSE_ERROR") from exc
    if not rows:
        raise NHIImportError("ZERO_ROWS")
    warnings = () if payload.startswith(b"\xef\xbb\xbf") else ("UTF8_BOM_ABSENT",)
    return NHIParseResult(rows=tuple(rows), warnings=warnings)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _write_immutable_json(path: Path, value: dict[str, Any]) -> None:
    payload = canonical_json_bytes(value)
    if path.exists():
        if path.read_bytes() != payload:
            raise NHIImportError("IMMUTABLE_CHECK_CONFLICT")
        return
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


def _file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


@lru_cache(maxsize=1)
def _package_build_sha256() -> str:
    try:
        installed = distribution("taiwan-laboratory-mcp")
    except PackageNotFoundError:
        installed = None

    if installed is not None and installed.files:
        record_text = installed.read_text("RECORD")
        inventory: list[dict[str, Any]] = []
        if record_text is not None:
            for name, expected_hash, expected_size in csv.reader(io.StringIO(record_text)):
                relative = PurePosixPath(name).as_posix()
                if relative.startswith("../"):
                    continue
                is_package_file = relative.startswith("taiwan_lab_mcp/")
                is_distribution_file = ".dist-info/" in relative and relative.rsplit("/", 1)[
                    -1
                ] in {
                    "METADATA",
                    "WHEEL",
                    "entry_points.txt",
                }
                if not (is_package_file or is_distribution_file):
                    continue
                path = installed.locate_file(name)
                if not path.is_file():
                    inventory = []
                    break
                content = path.read_bytes()
                try:
                    expected_digest = (
                        base64.urlsafe_b64decode(expected_hash.split("=", 1)[1] + "===")
                        if expected_hash
                        else None
                    )
                except (IndexError, ValueError):
                    inventory = []
                    break
                if expected_hash and (
                    not expected_hash.startswith("sha256=")
                    or hashlib.sha256(content).digest() != expected_digest
                ):
                    inventory = []
                    break
                if expected_size and len(content) != int(expected_size):
                    inventory = []
                    break
                inventory.append(
                    {"path": relative, "bytes": len(content), "sha256": sha256_bytes(content)}
                )
        required = {
            "taiwan_lab_mcp/contracts/public-contract-v1.json",
            "taiwan_lab_mcp/schemas/nhi_fee/nhi-7-v1.json",
        }
        if inventory and required.issubset({entry["path"] for entry in inventory}):
            return sha256_json(
                {"inventory_schema": "distribution-inventory-v1", "files": inventory}
            )

    package_root = files("taiwan_lab_mcp")
    inventory: list[dict[str, str]] = []

    def collect(node: Any, relative: str = "") -> None:
        for child in sorted(node.iterdir(), key=lambda item: item.name):
            if child.name == "__pycache__" or child.name.endswith(".pyc"):
                continue
            child_relative = f"{relative}/{child.name}" if relative else child.name
            if child.is_dir():
                collect(child, child_relative)
            elif child.is_file():
                inventory.append(
                    {"path": child_relative, "sha256": sha256_bytes(child.read_bytes())}
                )

    collect(package_root)
    return sha256_json({"inventory_schema": "development-package-inventory-v1", "files": inventory})


def build_nhi_snapshot(payload: bytes, data_root: Path) -> dict[str, Any]:
    """Build a small immutable NHI serving snapshot from caller-supplied bytes.

    The function is intentionally offline: it accepts bytes already obtained by the
    caller and never performs network access. Production source qualification remains
    an owner/reviewer gate outside this first vertical slice.
    """

    parsed = parse_nhi_csv(payload)
    data_root = Path(data_root)
    scope_bundle_bytes = (
        files("taiwan_lab_mcp").joinpath("rules", "nhi_lab_scope", "v1.json").read_bytes()
    )
    alias_bundle_bytes = (
        files("taiwan_lab_mcp").joinpath("rules", "nhi_aliases", "v1.json").read_bytes()
    )
    scope_rules = parse_scope_bundle(scope_bundle_bytes)
    parse_alias_bundle(alias_bundle_bytes)
    scope_rules_by_code = {search_normalize(code): rule for code, rule in scope_rules.items()}
    raw_digest = sha256_bytes(payload)
    discovery_identity = {
        "landing_url": "https://data.gov.tw/dataset/174450",
        "publisher_oid": "A21030000I",
        "dataset_id": "174450",
        "license_name": "政府資料開放授權條款－第 1 版",
        "license_url": "https://data.gov.tw/license",
        "official_version_label_raw": None,
        "official_modified_at_raw": None,
        "official_modified_at_precision": None,
        "official_modified_timezone_known": False,
    }
    raw_revision_id = nhi_raw_revision_id(
        payload_sha256=raw_digest,
        payload_size=len(payload),
        discovery=discovery_identity,
        media_type_verified="text/csv",
    )
    application_build_hash = _package_build_sha256()
    build_fingerprint = {
        "fingerprint_schema": "curated-build-v1",
        "source_id": "nhi_fee",
        "raw_revision_id": raw_revision_id,
        "application_build_sha256": application_build_hash,
        "parser": {"version": "nhi-csv-v1", "bundle_sha256": sha256_json(list(NHI_COLUMNS))},
        "schema": {"version": "nhi-7-v1", "bundle_sha256": sha256_json(list(NHI_COLUMNS))},
        "normalization": {
            "version": "text-v1",
            "bundle_sha256": sha256_json({"rule": "NFKC-casefold-whitespace"}),
        },
        "rules": [
            {
                "name": "nhi_lab_scope",
                "version": "nhi-lab-scope-v1",
                "bundle_sha256": sha256_bytes(scope_bundle_bytes),
            },
            {
                "name": "nhi_aliases",
                "version": "nhi-aliases-v1",
                "bundle_sha256": sha256_bytes(alias_bundle_bytes),
            },
        ],
        "qualifier": {
            "name": None,
            "version": None,
            "spec_sha256": None,
            "extractor_output_sha256": None,
        },
    }
    build_hash = sha256_json(build_fingerprint)
    build_id = f"nhi_fee-build-{build_hash}"

    build_dir = data_root / "curated" / "nhi_fee" / build_id
    if build_dir.exists():
        raise NHIImportError("IMMUTABLE_BUILD_EXISTS")

    raw_dir = data_root / "raw" / "nhi_fee" / raw_revision_id / "artifacts"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "source.csv"
    if raw_path.exists() and raw_path.read_bytes() != payload:
        raise NHIImportError("IMMUTABLE_RAW_CONFLICT")
    raw_path.write_bytes(payload)

    build_dir.mkdir(parents=True, exist_ok=True)
    db_path = build_dir / "data.sqlite3"
    if db_path.exists():
        raise NHIImportError("IMMUTABLE_BUILD_EXISTS")
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute(
            """
            CREATE TABLE nhi_fee (
                source_row_sha256 TEXT PRIMARY KEY,
                source_row_number INTEGER NOT NULL,
                code_raw TEXT NOT NULL,
                code_normalized TEXT NOT NULL,
                points_raw TEXT NOT NULL,
                points INTEGER NOT NULL,
                effective_start_raw TEXT NOT NULL,
                effective_start TEXT NOT NULL,
                effective_end_raw TEXT NOT NULL,
                effective_end TEXT NOT NULL,
                possible_open_end_sentinel INTEGER NOT NULL,
                name_zh_raw TEXT,
                name_zh_search TEXT,
                name_en_raw TEXT,
                name_en_search TEXT,
                note_raw TEXT,
                note_search TEXT,
                scope_status TEXT NOT NULL,
                scope_rule_version TEXT NOT NULL,
                scope_basis_locator TEXT
            )
            """
        )
        connection.executemany(
            "INSERT INTO nhi_fee VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    row.source_row_sha256,
                    row.source_row_number,
                    row.code_raw,
                    row.code_normalized,
                    row.points_raw,
                    row.points,
                    row.effective_start_raw,
                    row.effective_start,
                    row.effective_end_raw,
                    row.effective_end,
                    int(row.possible_open_end_sentinel),
                    row.name_zh_raw or None,
                    search_normalize(row.name_zh_raw) or None,
                    row.name_en_raw or None,
                    search_normalize(row.name_en_raw) or None,
                    row.note_raw or None,
                    search_normalize(row.note_raw) or None,
                    (
                        scope_rules_by_code[row.code_normalized].scope_status
                        if row.code_normalized in scope_rules_by_code
                        else "review_pending"
                    ),
                    "nhi-lab-scope-v1",
                    (
                        scope_rules_by_code[row.code_normalized].basis_locator
                        if row.code_normalized in scope_rules_by_code
                        else None
                    ),
                )
                for row in parsed.rows
            ],
        )
        connection.commit()
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise NHIImportError("SQLITE_INTEGRITY_FAILURE")
    finally:
        connection.close()

    db_digest = _file_sha256(db_path)
    fetched_at = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    validation = {
        "validation_schema_version": 1,
        "source_id": "nhi_fee",
        "raw_revision_id": raw_revision_id,
        "curated_build_id": build_id,
        "build_fingerprint_sha256": build_hash,
        "curated_db_sha256": db_digest,
        "artifact_hashes": [
            {
                "artifact_id": "nhi-primary-csv",
                "role": "primary",
                "sha256": raw_digest,
            }
        ],
        "row_counts": {
            "input_rows": len(parsed.rows),
            "curated_rows": len(parsed.rows),
            "quarantined_rows": 0,
        },
        "automated_status": "passed",
        "synthetic_ci_status": "passed",
        "blocking_errors": [],
        "warnings": list(parsed.warnings),
    }
    candidate = {
        "qualification_candidate_schema_version": 1,
        "source_id": "nhi_fee",
        "raw_revision_id": raw_revision_id,
        "curated_build_id": build_id,
        "case_ids": [],
        "cases": [],
        "automated_status": "passed",
        "synthetic_ci_status": "passed",
        "official_qualification_status": "not_qualified",
        "note": "offline synthetic fixture; not official qualification evidence",
    }
    validation_relative = f"curated/nhi_fee/{build_id}/audit/validation.json"
    candidate_relative = f"curated/nhi_fee/{build_id}/audit/qualification-candidate.json"
    validation_path = data_root / PurePosixPath(validation_relative)
    candidate_path = data_root / PurePosixPath(candidate_relative)
    _write_immutable_json(validation_path, validation)
    _write_immutable_json(candidate_path, candidate)
    validation_digest = _file_sha256(validation_path)
    candidate_digest = _file_sha256(candidate_path)
    manifest = {
        "manifest_schema_version": 1,
        "snapshot_id": build_id,
        "raw_revision_id": raw_revision_id,
        "curated_build_id": build_id,
        "build_fingerprint_sha256": build_hash,
        "build_fingerprint": build_fingerprint,
        "discovery_metadata_sha256": nhi_discovery_metadata_sha256(discovery_identity),
        "review_subject_digest": None,
        "source_id": "nhi_fee",
        "state": "approved",
        "source": {
            "provider": "衛生福利部中央健康保險署",
            "dataset_name": "醫療服務給付項目及支付標準(csv檔)",
            "dataset_id": "174450",
            "identifier": "A21030000I-D20021",
            "landing_url": "https://data.gov.tw/dataset/174450",
            "resource_url": "https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId=A21030000I-D20021-001",
            "license_name": "政府資料開放授權條款－第 1 版",
            "license_url": "https://data.gov.tw/license",
            "attribution": "資料提供機關：衛生福利部中央健康保險署",
        },
        "official_version": {
            "label": None,
            "modified_at_raw": None,
            "modified_at_precision": "unknown",
            "timezone_known": False,
        },
        "fetched_at": fetched_at,
        "artifacts": [
            {
                "artifact_id": "nhi-primary-csv",
                "role": "primary",
                "resource_url": "https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId=A21030000I-D20021-001",
                "storage_scope": "data_root",
                "data_root_relative_path": f"raw/nhi_fee/{raw_revision_id}/artifacts/source.csv",
                "local_artifact_available": True,
                "media_type_verified": "text/csv",
                "bytes": len(payload),
                "sha256": raw_digest,
            }
        ],
        "transform": {
            "application_build_sha256": application_build_hash,
            "parser": {"version": "nhi-csv-v1", "bundle_sha256": sha256_json(list(NHI_COLUMNS))},
            "schema": {"version": "nhi-7-v1", "bundle_sha256": sha256_json(list(NHI_COLUMNS))},
            "normalization": {
                "version": "text-v1",
                "bundle_sha256": sha256_json({"rule": "NFKC-casefold-whitespace"}),
            },
            "rules": build_fingerprint["rules"],
        },
        "counts": {
            "input_rows": len(parsed.rows),
            "curated_rows": len(parsed.rows),
            "quarantined_rows": 0,
        },
        "validation": {
            "automated_validation_status": "passed",
            "blocking_errors": [],
            "warnings": list(parsed.warnings),
        },
        "review": {
            "human_review_status": "approved",
            "required_gates": ["NHI-R1-SOURCE", "NHI-R1-SCHEMA"],
            "completed_gates": ["NHI-R1-SOURCE", "NHI-R1-SCHEMA"],
            "capability_reviews": [
                {"capability": "nhi_lab_scope", "gate_id": "NHI-R1-SCOPE", "status": "pending"}
            ],
        },
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
        "publication": {
            "curated_build_relative_path": f"curated/nhi_fee/{build_id}/data.sqlite3",
            "curated_sha256": db_digest,
        },
    }
    subject_digest = compute_review_subject_digest(
        manifest,
        curated_db_sha256=db_digest,
        validation_report_sha256=validation_digest,
        qualification_candidate_sha256=candidate_digest,
    )
    manifest["review_subject_digest"] = subject_digest
    review_evidence_refs = [
        {
            "artifact_id": "nhi-primary-csv",
            "path": f"raw/nhi_fee/{raw_revision_id}/artifacts/source.csv",
            "locator": {"kind": "source_artifact"},
            "sha256": raw_digest,
        },
        {
            "artifact_id": "nhi-curated-db",
            "path": f"curated/nhi_fee/{build_id}/data.sqlite3",
            "locator": {"kind": "sqlite_snapshot"},
            "sha256": db_digest,
        },
        {
            "artifact_id": "nhi-validation",
            "path": validation_relative,
            "locator": {"kind": "validation_report"},
            "sha256": validation_digest,
        },
        {
            "artifact_id": "nhi-qualification-candidate",
            "path": candidate_relative,
            "locator": {"kind": "qualification_candidate"},
            "sha256": candidate_digest,
        },
    ]
    protocol_sha256 = sha256_json(
        {"protocol_id": "nhi-r1-synthetic-fixture", "protocol_version": "1"}
    )
    for gate_id in manifest["review"]["completed_gates"]:
        review = {
            "review_schema_version": 1,
            "gate_id": gate_id,
            "decision": "approved",
            "source_id": "nhi_fee",
            "curated_build_id": build_id,
            "subject_digest": subject_digest,
            "reviewer_id": "offline-test-builder",
            "reviewer_role": "test_fixture_reviewer",
            "identity_assurance": "local_asserted",
            "reviewed_at": fetched_at,
            "protocol_id": "nhi-r1-synthetic-fixture",
            "protocol_version": "1",
            "protocol_sha256": protocol_sha256,
            "review_scope": {"kind": "synthetic_fixture", "row_count": len(parsed.rows)},
            "evidence_refs": review_evidence_refs,
            "finding_counts": {"critical": 0, "major": 0, "minor": 0},
            "comments": "Synthetic fixture review only; not official source qualification.",
            "signature": None,
        }
        review_relative = f"curated/nhi_fee/{build_id}/audit/reviews/{gate_id}.json"
        review_path = data_root / PurePosixPath(review_relative)
        _write_immutable_json(review_path, review)
        manifest["audit_evidence"]["reviews"].append(
            {
                "gate_id": gate_id,
                "data_root_relative_path": review_relative,
                "sha256": _file_sha256(review_path),
            }
        )
    golden = {
        "qualification_certificate_schema_version": 1,
        "source_id": "nhi_fee",
        "curated_build_id": build_id,
        "subject_digest": subject_digest,
        "candidate_report_sha256": candidate_digest,
        "accepted_review_hashes": [
            item["sha256"] for item in manifest["audit_evidence"]["reviews"]
        ],
        "approved_distinct_case_ids": [],
        "official_qualification_status": "not_qualified",
    }
    golden_relative = f"curated/nhi_fee/{build_id}/audit/golden-qualification.json"
    golden_path = data_root / PurePosixPath(golden_relative)
    _write_immutable_json(golden_path, golden)
    manifest["audit_evidence"]["golden_qualification"] = {
        "data_root_relative_path": golden_relative,
        "sha256": _file_sha256(golden_path),
    }
    manifest_path = build_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    manifest_digest = _file_sha256(manifest_path)
    check_id = f"nhi_fee-check-{build_hash}"
    check_relative_path = f"checks/nhi_fee/{check_id}.json"
    check = {
        "check_schema_version": 1,
        "check_id": check_id,
        "source_id": "nhi_fee",
        "generation": 1,
        "serving_snapshot_id": build_id,
        "serving_curated_build_id": build_id,
        "checked_at": fetched_at,
        "latest_seen_version": None,
        "latest_seen_artifact_sha256": raw_digest,
        "latest_candidate_id": None,
        "latest_candidate_status": "none",
        "check_result": "success",
        "failed_stage": None,
        "error_code": None,
        "stale": False,
        "stale_reason_codes": [],
        "freshness_policy_version": "nhi-v1",
        "content_age_status": "unknown",
        "content_age_evidence": None,
    }
    check_path = data_root / check_relative_path
    _write_immutable_json(check_path, check)
    check_digest = _file_sha256(check_path)
    descriptor = {
        "descriptor_schema_version": 1,
        "source_id": "nhi_fee",
        "generation": 1,
        "serving_snapshot_id": build_id,
        "serving_curated_build_id": build_id,
        "manifest_data_root_relative_path": f"curated/nhi_fee/{build_id}/manifest.json",
        "manifest_sha256": manifest_digest,
        "parent_snapshot_id": None,
        "last_successful_publish_at": fetched_at,
        "publisher_actor_id": "offline-test-builder",
        "last_check_at": fetched_at,
        "last_successful_check_at": fetched_at,
        "latest_seen_version": None,
        "latest_seen_artifact_sha256": raw_digest,
        "latest_candidate_id": None,
        "latest_candidate_status": "none",
        "check_result": "success",
        "failed_stage": None,
        "error_code": None,
        "stale": False,
        "stale_reason_codes": [],
        "freshness_policy_version": "nhi-v1",
        "content_age_status": "unknown",
        "content_age_evidence": None,
        "latest_check_data_root_relative_path": check_relative_path,
        "latest_check_sha256": check_digest,
    }
    publish_current_descriptor(
        data_root,
        descriptor,
        expected_generation=0,
        expected_parent_snapshot_id=None,
        actor="offline-test-builder",
    )
    return {
        "snapshot_id": build_id,
        "raw_revision_id": raw_revision_id,
        "rows": len(parsed.rows),
        "db_sha256": db_digest,
    }
