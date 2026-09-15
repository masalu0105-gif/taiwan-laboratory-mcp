"""TFDA medical device permit CSV-in-ZIP: archive safety, strict 34-column parse, curated build.

Validation reads caller-supplied ZIP bytes and never fetches. A curated build keeps every
source row with its IVD label in SQLite; the official build needs owner reviews (SDD 10.2).
"""

from __future__ import annotations

import codecs
import csv
import io
import json
import os
import re
import sqlite3
import tempfile
import zipfile
import zlib
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

from ..audit import _sha256_file, compute_review_subject_digest
from ..canonical import canonical_json_bytes, sha256_bytes, sha256_json
from ..models import GoldenCaseV1
from ..publish import publish_current_descriptor
from ..rules.tfda import (
    ACTIVE_IVD_RULE_VERSION,
    IvdDecision,
    cancellation_consistency,
    classification_codes,
    derive_ivd_scope,
    main_category_letters,
    packaged_ivd_registry_bytes,
    parse_ivd_registry,
)
from ..util import search_normalize, tfda_search_normalize

TFDA_SOURCE_ID = "tfda_devices"
TFDA_COLUMNS = (
    "許可證字號",
    "註銷狀態",
    "註銷日期",
    "註銷理由",
    "有效日期",
    "發證日期",
    "許可證種類",
    "舊證字號",
    "醫療器材級數",
    "通關簽審文件編號",
    "中文品名",
    "英文品名",
    "效能",
    "劑型",
    "包裝",
    "醫器主類別一",
    "醫器次類別一",
    "醫器主類別二",
    "醫器次類別二",
    "醫器主類別三",
    "醫器次類別三",
    "主成分略述",
    "醫器規格",
    "限制項目",
    "申請商名稱",
    "申請商地址",
    "申請商統一編號",
    "製造商名稱",
    "製造廠廠址",
    "製造廠公司地址",
    "製造廠國別",
    "製程",
    "異動日期",
    "製造許可登錄編號",
)
TFDA_DATE_COLUMNS = ("註銷日期", "有效日期", "發證日期", "異動日期")
TFDA_PARSER_VERSION = "tfda-csv-v1"
TFDA_SCHEMA_VERSION = "tfda-34-v1"

MIB = 1024 * 1024
MAX_ZIP_BYTES = 64 * MIB
MAX_UNCOMPRESSED_BYTES = 256 * MIB
MAX_COMPRESSION_RATIO = 30
_READ_CHUNK = MIB
_ZIP_MAGIC = b"PK\x03\x04"
_DATE_RE = re.compile(r"^([0-9]{4})/([0-9]{2})/([0-9]{2})$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_SYMLINK_MODE = 0o120000


class TFDAImportError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}{(': ' + detail) if detail else ''}")


@dataclass(frozen=True)
class TFDAArchiveEntry:
    name: str
    payload: bytes
    payload_sha256: str
    zip_sha256: str
    zip_bytes: int
    compressed_bytes: int
    uncompressed_bytes: int


@dataclass(frozen=True)
class TFDASourceRow:
    source_row_number: int
    source_row_sha256: str
    values: dict[str, str]


@dataclass(frozen=True)
class TFDAParseResult:
    rows: tuple[TFDASourceRow, ...]
    header_sha256: str
    warnings: tuple[str, ...]


def _entry_path_is_unsafe(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or _DRIVE_RE.match(normalized):
        return True
    return any(part == ".." for part in PurePosixPath(normalized).parts)


def extract_tfda_csv(
    payload: bytes,
    *,
    max_zip_bytes: int = MAX_ZIP_BYTES,
    max_uncompressed_bytes: int = MAX_UNCOMPRESSED_BYTES,
    max_ratio: int = MAX_COMPRESSION_RATIO,
) -> TFDAArchiveEntry:
    """Return the single CSV entry after checking the archive boundary (SDD 10.2)."""

    if not isinstance(payload, bytes) or not payload:
        raise TFDAImportError("ARCHIVE_EMPTY")
    if len(payload) > max_zip_bytes:
        raise TFDAImportError("ARCHIVE_SIZE_LIMIT", "compressed archive")
    if not payload.startswith(_ZIP_MAGIC):
        raise TFDAImportError("CONTENT_MAGIC_MISMATCH")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise TFDAImportError("ARCHIVE_CORRUPT") from exc
    with archive:
        entries = archive.infolist()
        if len(entries) != 1:
            raise TFDAImportError("ARCHIVE_ENTRY_COUNT", str(len(entries)))
        info = entries[0]
        if _entry_path_is_unsafe(info.filename):
            raise TFDAImportError("ARCHIVE_PATH_TRAVERSAL")
        if info.is_dir() or (info.external_attr >> 16) & 0o170000 == _SYMLINK_MODE:
            raise TFDAImportError("ARCHIVE_ENTRY_TYPE", "not a regular file")
        if info.flag_bits & 0x1:
            raise TFDAImportError("ARCHIVE_ENTRY_TYPE", "encrypted entry")
        if not info.filename.lower().endswith(".csv"):
            raise TFDAImportError("ARCHIVE_ENTRY_TYPE", "entry extension is not .csv")
        ratio_limit = max_ratio * max(info.compress_size, 1)
        chunks: list[bytes] = []
        total = 0
        try:
            with archive.open(info) as stream:
                while True:
                    chunk = stream.read(_READ_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    # Count bytes actually streamed; declared sizes are not trusted.
                    if total > max_uncompressed_bytes:
                        raise TFDAImportError("ARCHIVE_SIZE_LIMIT", "uncompressed entry")
                    if total > ratio_limit:
                        raise TFDAImportError("ARCHIVE_RATIO_LIMIT")
                    chunks.append(chunk)
        except TFDAImportError:
            raise
        except (zipfile.BadZipFile, zlib.error, EOFError, OSError, RuntimeError) as exc:
            raise TFDAImportError("ARCHIVE_CORRUPT") from exc
        except NotImplementedError as exc:
            raise TFDAImportError("ARCHIVE_ENTRY_TYPE", "unsupported compression") from exc
        if total != info.file_size:
            raise TFDAImportError("ARCHIVE_CORRUPT", "declared size mismatch")
    content = b"".join(chunks)
    return TFDAArchiveEntry(
        name=info.filename,
        payload=content,
        payload_sha256=sha256_bytes(content),
        zip_sha256=sha256_bytes(payload),
        zip_bytes=len(payload),
        compressed_bytes=info.compress_size,
        uncompressed_bytes=total,
    )


def _date_is_valid(value: str) -> bool:
    match = _DATE_RE.fullmatch(value)
    if match is None:
        return False
    try:
        date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return False
    return True


_PERMIT_INDEX = TFDA_COLUMNS.index("許可證字號")
_CANCELLATION_STATUS_INDEX = TFDA_COLUMNS.index("註銷狀態")
_VALID_THROUGH_INDEX = TFDA_COLUMNS.index("有效日期")
_DATE_INDEXES = tuple((column, TFDA_COLUMNS.index(column)) for column in TFDA_DATE_COLUMNS)
_REPLACEMENT_CHARACTER = chr(0xFFFD)


def _iter_tfda_records(payload: bytes):
    """Yield (source_row_number, raw values) after the strict checks, one record at a time."""

    if not isinstance(payload, bytes) or not payload:
        raise TFDAImportError("EMPTY_INPUT")
    if 0 in payload:
        raise TFDAImportError("NUL_BYTE")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TFDAImportError("DECODE_ERROR") from exc
    if _REPLACEMENT_CHARACTER in text:
        raise TFDAImportError("DECODE_REPLACEMENT_CHARACTER")

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise TFDAImportError("ZERO_ROWS") from exc
    except csv.Error as exc:
        raise TFDAImportError("CSV_PARSE_ERROR") from exc
    if header != list(TFDA_COLUMNS):
        if len(header) != len(set(header)):
            raise TFDAImportError("SCHEMA_DUPLICATE_COLUMN")
        raise TFDAImportError("SCHEMA_HEADER_MISMATCH")

    try:
        for source_row_number, values in enumerate(reader, start=2):
            location = f"source row {source_row_number}"
            if not values or all(value == "" for value in values):
                raise TFDAImportError("MALFORMED_RECORD", location)
            if values == list(TFDA_COLUMNS):
                raise TFDAImportError("SCHEMA_DUPLICATE_HEADER", location)
            if len(values) != len(TFDA_COLUMNS):
                raise TFDAImportError("ROW_WIDTH_MISMATCH", location)
            if not values[_PERMIT_INDEX].strip() or values[_VALID_THROUGH_INDEX] == "":
                raise TFDAImportError("REQUIRED_VALUE_MISSING", location)
            for column, index in _DATE_INDEXES:
                if values[index] != "" and not _date_is_valid(values[index]):
                    raise TFDAImportError("DATE_INVALID", f"{column} {location}")
            yield source_row_number, values
    except csv.Error as exc:
        raise TFDAImportError("CSV_PARSE_ERROR") from exc


def _utf8_warnings(payload: bytes) -> tuple[str, ...]:
    return () if payload.startswith(codecs.BOM_UTF8) else ("UTF8_BOM_ABSENT",)


def parse_tfda_csv(payload: bytes) -> TFDAParseResult:
    rows = [
        TFDASourceRow(
            source_row_number=source_row_number,
            source_row_sha256=sha256_bytes(canonical_json_bytes(list(values))),
            values=dict(zip(TFDA_COLUMNS, values)),
        )
        for source_row_number, values in _iter_tfda_records(payload)
    ]
    if not rows:
        raise TFDAImportError("ZERO_ROWS")
    return TFDAParseResult(
        rows=tuple(rows),
        header_sha256=sha256_bytes(canonical_json_bytes(list(TFDA_COLUMNS))),
        warnings=_utf8_warnings(payload),
    )


def summarize_tfda_csv(entry: TFDAArchiveEntry) -> dict[str, Any]:
    """Same checks and summary as parse + tfda_validation_summary, without keeping rows.

    The official file has about 105,000 rows; holding every row as a dict failed with
    MemoryError on a machine low on commit memory (2026-09-14).
    """

    permits: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    empty_counts = dict.fromkeys(TFDA_COLUMNS, 0)
    rows = 0
    for _, values in _iter_tfda_records(entry.payload):
        rows += 1
        permits[search_normalize(values[_PERMIT_INDEX])] += 1
        statuses[values[_CANCELLATION_STATUS_INDEX]] += 1
        for column, value in zip(TFDA_COLUMNS, values):
            if value == "":
                empty_counts[column] += 1
    if rows == 0:
        raise TFDAImportError("ZERO_ROWS")
    return {
        "rows": rows,
        "distinct_license_numbers": len(permits),
        "license_numbers_with_multiple_rows": sum(1 for count in permits.values() if count > 1),
        "max_rows_per_license_number": max(permits.values()),
        "cancellation_status_counts": dict(sorted(statuses.items())),
        "empty_value_counts": empty_counts,
        "header_sha256": sha256_bytes(canonical_json_bytes(list(TFDA_COLUMNS))),
        "warnings": list(_utf8_warnings(entry.payload)),
        "archive": {
            "zip_bytes": entry.zip_bytes,
            "zip_sha256": entry.zip_sha256,
            "entry_name": entry.name,
            "entry_bytes": entry.uncompressed_bytes,
            "entry_sha256": entry.payload_sha256,
        },
    }


def tfda_validation_summary(entry: TFDAArchiveEntry, parsed: TFDAParseResult) -> dict[str, Any]:
    """Counts that serve as the drift baseline; the permit number is only a group key."""

    permits = Counter(search_normalize(row.values["許可證字號"]) for row in parsed.rows)
    statuses = Counter(row.values["註銷狀態"] for row in parsed.rows)
    return {
        "rows": len(parsed.rows),
        "distinct_license_numbers": len(permits),
        "license_numbers_with_multiple_rows": sum(1 for count in permits.values() if count > 1),
        "max_rows_per_license_number": max(permits.values()),
        "cancellation_status_counts": dict(sorted(statuses.items())),
        "empty_value_counts": {
            column: sum(1 for row in parsed.rows if row.values[column] == "")
            for column in TFDA_COLUMNS
        },
        "header_sha256": parsed.header_sha256,
        "warnings": list(parsed.warnings),
        "archive": {
            "zip_bytes": entry.zip_bytes,
            "zip_sha256": entry.zip_sha256,
            "entry_name": entry.name,
            "entry_bytes": entry.uncompressed_bytes,
            "entry_sha256": entry.payload_sha256,
        },
    }


def run_tfda_offline_validation(payload: bytes, data_root: Path, *, clock=None) -> dict[str, Any]:
    """Validate caller-supplied ZIP bytes and write only a staged report.

    Offline input has no upstream provenance, so no raw revision, candidate, curated
    build or current descriptor is created.
    """

    from ..sync import _attempt_id, _utc_now, _write_immutable_json

    data_root = Path(data_root)
    started_at = _utc_now(clock)
    attempt_id = _attempt_id(TFDA_SOURCE_ID, None, started_at)
    report_relative = str(PurePosixPath("staged", TFDA_SOURCE_ID, attempt_id, "validation.json"))
    stage = "archive"
    error_code = None
    summary = None
    try:
        entry = extract_tfda_csv(payload)
        stage = "parse"
        summary = summarize_tfda_csv(entry)
        stage = "validate"
    except TFDAImportError as exc:
        error_code = exc.code
    except MemoryError:
        error_code = "RESOURCE_EXHAUSTED"
    completed_at = _utc_now(clock)
    report = {
        "sync_report_schema_version": 1,
        "attempt_id": attempt_id,
        "source_id": TFDA_SOURCE_ID,
        "input_kind": "offline_input",
        "stage": stage,
        "status": "failed" if error_code else "passed",
        "error_code": error_code,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "raw_revision_id": None,
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


TFDA_FIELD_NAMES = (
    "license_no_raw",
    "cancellation_status_raw",
    "cancellation_date_raw",
    "cancellation_reason_raw",
    "valid_through_raw",
    "issued_on_raw",
    "license_kind_raw",
    "legacy_license_no_raw",
    "risk_class_raw",
    "customs_document_no_raw",
    "name_zh_raw",
    "name_en_raw",
    "effect_raw",
    "dosage_form_raw",
    "package_raw",
    "main_category_1_raw",
    "sub_category_1_raw",
    "main_category_2_raw",
    "sub_category_2_raw",
    "main_category_3_raw",
    "sub_category_3_raw",
    "main_ingredient_raw",
    "specification_raw",
    "restriction_raw",
    "applicant_name_raw",
    "applicant_address_raw",
    "applicant_tax_id_raw",
    "manufacturer_name_raw",
    "factory_address_raw",
    "manufacturer_company_address_raw",
    "manufacturer_country_raw",
    "process_raw",
    "changed_on_raw",
    "manufacturing_registration_no_raw",
)
TFDA_PRIMARY_ARTIFACT_ID = "tfda-primary-zip"
TFDA_RESOURCE_URL = "https://data.fda.gov.tw/data/opendata/export/68/csv"
TFDA_PROVIDER = "衛生福利部食品藥物管理署"
TFDA_DATASET_NAME = "醫療器材許可證資料集"
TFDA_ATTRIBUTION = "資料提供機關：衛生福利部食品藥物管理署"
TFDA_NORMALIZATION_VERSION = "tfda-text-v1"
TFDA_SERVING_GATES = ("TFDA-R1-SOURCE", "TFDA-R1-SCHEMA", "PUB-R1-OWNER")
# Owner 2026-09-15 delegated the TFDA launch review to AI ("你直接幫我審核").
# Version 2 (owner 2026-09-15): the reviewed build may also be a GitHub Release bundle.
TFDA_REVIEW_PROTOCOL_ID = "tfda-r1-ai-review"
TFDA_REVIEW_PROTOCOL_VERSION = "2"
# Owner 2026-09-15 chose automatic weekly updates ("A變成成自動化 我不想花太多心力維護").
TFDA_AUTO_REVIEW_PROTOCOL_ID = "tfda-r1-auto-review"
TFDA_AUTO_REVIEW_PROTOCOL_VERSION = "2"
_DELEGATED_REVIEW_PROTOCOLS = frozenset(
    {
        (TFDA_REVIEW_PROTOCOL_ID, TFDA_REVIEW_PROTOCOL_VERSION),
        (TFDA_AUTO_REVIEW_PROTOCOL_ID, TFDA_AUTO_REVIEW_PROTOCOL_VERSION),
    }
)
_MINIMUM_OFFICIAL_GOLDEN_CASES = 10
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
_OWNER_REVIEW_KEYS = frozenset(
    {"gate_id", "reviewer_id", "reviewer_role", "reviewed_at", "finding_counts", "comments"}
)
_SEARCH_COLUMNS = (
    ("license_no_search", "license_no_raw"),
    ("name_zh_search", "name_zh_raw"),
    ("name_en_search", "name_en_raw"),
    ("applicant_name_search", "applicant_name_raw"),
    ("manufacturer_name_search", "manufacturer_name_raw"),
    ("effect_search", "effect_raw"),
)
_MAIN_FIELDS = ("main_category_1_raw", "main_category_2_raw", "main_category_3_raw")
_SUB_FIELDS = ("sub_category_1_raw", "sub_category_2_raw", "sub_category_3_raw")
TFDA_ROW_COLUMNS = (
    "source_row_sha256",
    "source_row_number",
    *TFDA_FIELD_NAMES,
    *(column for column, _ in _SEARCH_COLUMNS),
    "classification_search",
    "cancellation_date",
    "valid_through",
    "cancellation_raw_nonempty",
    "main_category_letters",
    "classification_codes",
    "ivd_scope",
    "ivd_rule_version",
)
_NULLABLE_COLUMNS = frozenset({"cancellation_date", "valid_through"})
_INTEGER_COLUMNS = frozenset({"source_row_number", "cancellation_raw_nonempty"})
TFDA_TABLE_SQL = "CREATE TABLE tfda_source_row ({})".format(
    ", ".join(
        f"{column} {'INTEGER' if column in _INTEGER_COLUMNS else 'TEXT'}"
        f"{'' if column in _NULLABLE_COLUMNS else ' NOT NULL'}"
        for column in TFDA_ROW_COLUMNS
    )
)
_CLASSIFICATION_TABLE_SQL = (
    "CREATE TABLE tfda_classification (source_row_sha256 TEXT NOT NULL, "
    "ordinal INTEGER NOT NULL, main_category_raw TEXT NOT NULL, sub_category_raw TEXT NOT NULL, "
    "main_category_letter TEXT, classification_code TEXT)"
)
_UNIQUE_INDEX_SQL = (
    "CREATE UNIQUE INDEX tfda_source_row_hash ON tfda_source_row (source_row_sha256)",
    "CREATE UNIQUE INDEX tfda_source_row_number ON tfda_source_row (source_row_number)",
    "CREATE UNIQUE INDEX tfda_classification_row "
    "ON tfda_classification (source_row_sha256, ordinal)",
)
_QUERY_SCHEMA_SQL = (
    "CREATE INDEX tfda_source_row_license ON tfda_source_row (license_no_search, source_row_number)",
    "CREATE VIEW tfda_permit_group AS SELECT license_no_search, COUNT(*) AS source_row_count, "
    "MIN(source_row_number) AS first_source_row_number FROM tfda_source_row "
    "GROUP BY license_no_search",
)
_INSERT_ROW_SQL = "INSERT INTO tfda_source_row ({}) VALUES ({})".format(
    ", ".join(TFDA_ROW_COLUMNS), ", ".join("?" for _ in TFDA_ROW_COLUMNS)
)
_INSERT_CLASSIFICATION_SQL = "INSERT INTO tfda_classification VALUES (?, ?, ?, ?, ?, ?)"
_INSERT_BATCH = 2000


def _iso_date(raw: str) -> str | None:
    # Official values already passed the strict YYYY/MM/DD check in _iter_tfda_records.
    return raw.replace("/", "-") if raw else None


def tfda_curated_row(
    source_row_number: int, values: Sequence[str], decisions: Mapping[str, IvdDecision]
) -> dict[str, Any]:
    """Return the stored columns: raw values unchanged, plus search columns and labels."""

    raw = dict(zip(TFDA_FIELD_NAMES, values))
    mains = [raw[name] for name in _MAIN_FIELDS]
    subs = [raw[name] for name in _SUB_FIELDS]
    codes = classification_codes(subs)
    row: dict[str, Any] = {
        "source_row_sha256": sha256_bytes(canonical_json_bytes(list(values))),
        "source_row_number": source_row_number,
        **raw,
    }
    for column, field in _SEARCH_COLUMNS:
        row[column] = tfda_search_normalize(raw[field])
    row.update(
        classification_search="\n".join(
            tfda_search_normalize(value) for value in (*mains, *subs) if value
        ),
        cancellation_date=_iso_date(raw["cancellation_date_raw"]),
        valid_through=_iso_date(raw["valid_through_raw"]),
        cancellation_raw_nonempty=int(bool(raw["cancellation_status_raw"].strip())),
        main_category_letters="".join(main_category_letters(mains)),
        classification_codes=json.dumps(codes),
        ivd_scope=derive_ivd_scope(codes, decisions),
        ivd_rule_version=ACTIVE_IVD_RULE_VERSION,
    )
    return row


class IvdCoverage:
    """IvdCoverageDetailV1 counts for one build (PRD 7.2.1)."""

    def __init__(self, decisions: Mapping[str, IvdDecision]) -> None:
        self._decisions = decisions
        self._codes: set[str] = set()
        self.legacy_code_rows = 0
        self.missing_code_rows = 0
        self.unknown_code_rows = 0

    def add(self, row: Mapping[str, Any]) -> None:
        codes = json.loads(row["classification_codes"])
        # The reviewed annex covers classes A, B and C; other letters are unreviewed codes.
        self._codes.update(code for code in codes if code[0] in "ABC")
        if codes:
            # Unreviewed A/B/C codes count as included (owner 2026-09-15), so only rows with
            # nothing but other classes stay unknown.
            if not any(code in self._decisions or code[0] in "ABC" for code in codes):
                self.unknown_code_rows += 1
        elif any(row[name].strip()[:1].isdigit() for name in (*_MAIN_FIELDS, *_SUB_FIELDS)):
            self.legacy_code_rows += 1
        else:
            self.missing_code_rows += 1

    def detail(self) -> dict[str, Any]:
        return {
            "reviewed_codes": sum(1 for code in self._codes if code in self._decisions),
            "total_codes": len(self._codes),
            "legacy_code_rows": self.legacy_code_rows,
            "missing_code_rows": self.missing_code_rows,
            "unknown_code_rows": self.unknown_code_rows,
            "rule_version": ACTIVE_IVD_RULE_VERSION,
        }


def _classification_rows(row: Mapping[str, Any]) -> Iterable[tuple[Any, ...]]:
    for ordinal, (main_field, sub_field) in enumerate(zip(_MAIN_FIELDS, _SUB_FIELDS), start=1):
        main, sub = row[main_field], row[sub_field]
        if main or sub:
            letters = main_category_letters([main])
            codes = classification_codes([sub])
            yield (
                row["source_row_sha256"],
                ordinal,
                main,
                sub,
                letters[0] if letters else None,
                codes[0] if codes else None,
            )


def create_tfda_schema(connection: sqlite3.Connection) -> None:
    connection.execute(TFDA_TABLE_SQL)
    connection.execute(_CLASSIFICATION_TABLE_SQL)


def finish_tfda_schema(connection: sqlite3.Connection, *, unique_rows: bool = True) -> None:
    """Add indexes after loading; the package sample path allows repeated fixture rows."""

    for statement in (*(_UNIQUE_INDEX_SQL if unique_rows else ()), *_QUERY_SCHEMA_SQL):
        connection.execute(statement)


def insert_tfda_rows(connection: sqlite3.Connection, rows: Sequence[Mapping[str, Any]]) -> None:
    connection.executemany(
        _INSERT_ROW_SQL, [tuple(row[column] for column in TFDA_ROW_COLUMNS) for row in rows]
    )
    connection.executemany(
        _INSERT_CLASSIFICATION_SQL, [item for row in rows for item in _classification_rows(row)]
    )


def _write_tfda_curated_db(
    db_path: Path, csv_payload: bytes, decisions: Mapping[str, IvdDecision]
) -> dict[str, Any]:
    """Stream every source row into SQLite and return the IVD coverage detail.

    Rows are inserted in batches so the ~105,000 official rows never sit in memory at once;
    the database appears under its final name only after the integrity check passes.
    """

    if db_path.exists():
        raise TFDAImportError("IMMUTABLE_BUILD_EXISTS")
    partial = db_path.with_name(f".{db_path.name}.partial")
    if partial.exists():
        partial.unlink()
    coverage = IvdCoverage(decisions)
    connection = sqlite3.connect(partial)
    succeeded = False
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        create_tfda_schema(connection)
        batch: list[dict[str, Any]] = []
        for source_row_number, values in _iter_tfda_records(csv_payload):
            row = tfda_curated_row(source_row_number, values, decisions)
            coverage.add(row)
            batch.append(row)
            if len(batch) == _INSERT_BATCH:
                insert_tfda_rows(connection, batch)
                batch = []
        insert_tfda_rows(connection, batch)
        finish_tfda_schema(connection)
        connection.commit()
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise TFDAImportError("SQLITE_INTEGRITY_FAILURE")
        succeeded = True
    except sqlite3.IntegrityError as exc:
        raise TFDAImportError("DUPLICATE_SOURCE_ROW") from exc
    finally:
        connection.close()
        if not succeeded and partial.exists():
            partial.unlink()
    os.replace(partial, db_path)
    return coverage.detail()


def _tfda_transform(registry_bytes: bytes) -> dict[str, Any]:
    return {
        "parser": {
            "version": TFDA_PARSER_VERSION,
            "bundle_sha256": sha256_json(list(TFDA_COLUMNS)),
        },
        "schema": {
            "version": TFDA_SCHEMA_VERSION,
            "bundle_sha256": sha256_json(
                {"columns": list(TFDA_COLUMNS), "curated_columns": list(TFDA_ROW_COLUMNS)}
            ),
        },
        "normalization": {
            "version": TFDA_NORMALIZATION_VERSION,
            "bundle_sha256": sha256_json({"rule": "NFKC-casefold-whitespace-quotes-tai"}),
        },
        "rules": [
            {
                "name": "tfda_ivd",
                "version": ACTIVE_IVD_RULE_VERSION,
                "bundle_sha256": sha256_bytes(registry_bytes),
            }
        ],
        "qualifier": {
            "name": None,
            "version": None,
            "spec_sha256": None,
            "extractor_output_sha256": None,
        },
    }


def active_tfda_transform() -> dict[str, Any]:
    """Return the parser/schema/normalization/rule identity a golden case must bind to."""

    return _tfda_transform(packaged_ivd_registry_bytes())


_GOLDEN_TFDA_FIELDS = frozenset(TFDA_FIELD_NAMES) | {
    "main_category_letters",
    "classification_codes",
    "ivd_scope",
}


def _golden_value(row: Mapping[str, Any], field: str) -> Any:
    if field == "main_category_letters":
        return list(row[field])
    if field == "classification_codes":
        return json.loads(row[field])
    return row[field]


def _golden_row_warnings(row: Mapping[str, Any]) -> list[str]:
    # Only the date-independent consistency warnings; validity depends on the query date.
    cancellation_date = (
        date.fromisoformat(row["cancellation_date"]) if row["cancellation_date"] else None
    )
    return cancellation_consistency(row["cancellation_status_raw"], cancellation_date)[1]


def _tfda_golden_failure_codes(
    case: GoldenCaseV1,
    rows_by_number: Mapping[int, dict[str, Any]],
    *,
    artifact_id: str,
    raw_artifact_sha256: str,
    transform: dict[str, Any],
) -> list[str]:
    codes: list[str] = []
    if case.source_id != TFDA_SOURCE_ID:
        codes.append("SOURCE_MISMATCH")
    if case.artifact_id != artifact_id or case.raw_artifact_sha256 != raw_artifact_sha256:
        codes.append("ARTIFACT_MISMATCH")
    if case.transform != transform:
        codes.append("TRANSFORM_MISMATCH")
    if case.expected_status != "ok":
        codes.append("EXPECTED_STATUS_UNSUPPORTED")
    if case.source_locator.locator_type != "tfda_row":
        codes.append("LOCATOR_UNSUPPORTED")
    if not case.expected_fields:
        codes.append("EXPECTED_FIELDS_EMPTY")
    codes.extend(
        f"EXPECTED_FIELD_UNSUPPORTED:{field}"
        for field in sorted(set(case.expected_fields) - _GOLDEN_TFDA_FIELDS)
    )
    license_no = case.input.get("license_no") if set(case.input) == {"license_no"} else None
    if not license_no or not tfda_search_normalize(license_no):
        codes.append("INPUT_UNSUPPORTED")
        return codes
    row = (
        rows_by_number.get(case.source_locator.source_row_number)
        if case.source_locator.locator_type == "tfda_row"
        else None
    )
    if row is None or row["license_no_search"] != tfda_search_normalize(license_no):
        codes.append("STATUS_MISMATCH")
        return codes
    if case.source_row_sha256 != row["source_row_sha256"]:
        codes.append("LOCATOR_MISMATCH")
    codes.extend(
        f"FIELD_MISMATCH:{field}"
        for field in sorted(set(case.expected_fields) & _GOLDEN_TFDA_FIELDS)
        if case.expected_fields[field] != _golden_value(row, field)
    )
    if case.expected_warnings != _golden_row_warnings(row):
        codes.append("WARNINGS_MISMATCH")
    return codes


def _tfda_golden_results(
    csv_payload: bytes,
    cases: Sequence[Mapping[str, Any]],
    *,
    artifact_id: str,
    raw_artifact_sha256: str,
    transform: dict[str, Any],
    decisions: Mapping[str, IvdDecision],
) -> list[dict[str, Any]]:
    validated: list[tuple[dict[str, Any], GoldenCaseV1]] = []
    try:
        for case in cases:
            case_bytes = canonical_json_bytes(dict(case))
            validated.append((json.loads(case_bytes), GoldenCaseV1.model_validate_json(case_bytes)))
    except (TypeError, ValueError) as exc:
        raise TFDAImportError("GOLDEN_CASE_SCHEMA_INVALID") from exc
    case_ids = [model.case_id for _, model in validated]
    if len(set(case_ids)) != len(case_ids):
        raise TFDAImportError("GOLDEN_CASE_SCHEMA_INVALID", "duplicate case_id")
    wanted = {
        model.source_locator.source_row_number
        for _, model in validated
        if model.source_locator.locator_type == "tfda_row"
    }
    rows_by_number: dict[int, dict[str, Any]] = {}
    if wanted:
        for source_row_number, values in _iter_tfda_records(csv_payload):
            if source_row_number in wanted:
                rows_by_number[source_row_number] = tfda_curated_row(
                    source_row_number, values, decisions
                )
    results = []
    for raw_case, model in validated:
        failure_codes = _tfda_golden_failure_codes(
            model,
            rows_by_number,
            artifact_id=artifact_id,
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


def evaluate_tfda_golden_cases(
    payload: bytes, cases: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Re-run golden cases against raw ZIP bytes; no network, writes or approval."""

    entry = extract_tfda_csv(payload)
    registry_bytes = packaged_ivd_registry_bytes()
    return _tfda_golden_results(
        entry.payload,
        cases,
        artifact_id=TFDA_PRIMARY_ARTIFACT_ID,
        raw_artifact_sha256=sha256_bytes(payload),
        transform=_tfda_transform(registry_bytes),
        decisions=parse_ivd_registry(registry_bytes),
    )


def _write_audit_json(path: Path, value: Mapping[str, Any]) -> str:
    payload = canonical_json_bytes(dict(value))
    if path.exists():
        if path.read_bytes() != payload:
            raise TFDAImportError("IMMUTABLE_AUDIT_CONFLICT")
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


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _current_generation(data_root: Path) -> tuple[int, str | None]:
    current_path = data_root / "manifests" / "current" / f"{TFDA_SOURCE_ID}.json"
    if not current_path.is_file():
        return 0, None
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
        return int(current["generation"]), current["serving_snapshot_id"]
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise TFDAImportError("CURRENT_POINTER_INTEGRITY") from exc


def _publish_tfda_build(
    data_root: Path,
    *,
    payload: bytes,
    csv_payload: bytes,
    summary: Mapping[str, Any],
    raw_revision_id: str,
    artifact_relative: str,
    fetch_relative: str | None,
    discovery: Mapping[str, Any],
    fetched_at: str,
    application_build_hash: str,
    registry_bytes: bytes,
    decisions: Mapping[str, IvdDecision],
    golden_results: list[dict[str, Any]],
    review_inputs: Sequence[Mapping[str, Any]],
    protocol: tuple[str, str, str],
    publisher_actor_id: str,
    evidence_inputs: Sequence[tuple[str, str, bytes]],
    official: bool,
    pre_publish_check: Callable[[Path], tuple[str, str, bytes]] | None = None,
) -> dict[str, Any]:
    """Write the curated build, its audit bundle and publish it with generation CAS."""

    raw_digest = sha256_bytes(payload)
    transform = _tfda_transform(registry_bytes)
    build_fingerprint = {
        "fingerprint_schema": "curated-build-v1",
        "source_id": TFDA_SOURCE_ID,
        "raw_revision_id": raw_revision_id,
        "application_build_sha256": application_build_hash,
        **transform,
    }
    build_hash = sha256_json(build_fingerprint)
    build_id = f"{TFDA_SOURCE_ID}-build-{build_hash}"
    build_prefix = f"curated/{TFDA_SOURCE_ID}/{build_id}"
    build_dir = data_root / PurePosixPath(build_prefix)
    if build_dir.exists():
        raise TFDAImportError("IMMUTABLE_BUILD_EXISTS")
    expected_generation, expected_parent = _current_generation(data_root)

    build_dir.mkdir(parents=True)
    db_relative = f"{build_prefix}/data.sqlite3"
    coverage = _write_tfda_curated_db(
        data_root / PurePosixPath(db_relative), csv_payload, decisions
    )
    db_digest = _sha256_file(data_root / PurePosixPath(db_relative))
    if pre_publish_check is not None:
        # Runs on the finished database before any audit record or pointer refers to it;
        # its report becomes review evidence.
        evidence_inputs = [
            *evidence_inputs,
            pre_publish_check(data_root / PurePosixPath(db_relative)),
        ]
    audit_prefix = f"{build_prefix}/audit"
    rows = summary["rows"]
    row_counts = {"input_rows": rows, "curated_rows": rows, "quarantined_rows": 0}
    artifact_hashes = [
        {"artifact_id": TFDA_PRIMARY_ARTIFACT_ID, "role": "primary", "sha256": raw_digest}
    ]
    synthetic_ci_status = "not_run" if official else "passed"
    validation = {
        "validation_schema_version": 1,
        "source_id": TFDA_SOURCE_ID,
        "raw_revision_id": raw_revision_id,
        "curated_build_id": build_id,
        "build_fingerprint_sha256": build_hash,
        "curated_db_sha256": db_digest,
        "artifact_hashes": artifact_hashes,
        "row_counts": row_counts,
        "automated_status": "passed",
        "synthetic_ci_status": synthetic_ci_status,
        "blocking_errors": [],
        "warnings": list(summary["warnings"]),
    }
    case_ids = [result["golden_case"]["case_id"] for result in golden_results]
    candidate = {
        "qualification_candidate_schema_version": 1,
        "source_id": TFDA_SOURCE_ID,
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
            "pre-review candidate for an owner-reviewed official TFDA build"
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

    registry_status = json.loads(registry_bytes.decode("utf-8"))["status"]
    ivd_review_status = (
        "approved"
        if registry_status == "complete" and coverage["reviewed_codes"] == coverage["total_codes"]
        else "pending"
    )
    modified_at_raw = discovery.get("official_modified_at_raw")
    manifest: dict[str, Any] = {
        "manifest_schema_version": 1,
        "snapshot_id": build_id,
        "raw_revision_id": raw_revision_id,
        "curated_build_id": build_id,
        "build_fingerprint_sha256": build_hash,
        "build_fingerprint": build_fingerprint,
        "discovery_metadata_sha256": sha256_json(dict(discovery)),
        "review_subject_digest": None,
        "source_id": TFDA_SOURCE_ID,
        "state": "approved",
        "source": {
            "provider": TFDA_PROVIDER,
            "dataset_name": TFDA_DATASET_NAME,
            "dataset_id": discovery["dataset_id"],
            "identifier": discovery["identifier"],
            "landing_url": discovery["landing_url"],
            "resource_url": discovery["resource_url"],
            "license_name": discovery["license_name"],
            "license_url": discovery["license_url"],
            "attribution": TFDA_ATTRIBUTION,
        },
        "official_version": {
            "label": None,
            "modified_at_raw": modified_at_raw,
            "modified_at_precision": "second" if modified_at_raw else "unknown",
            "timezone_known": discovery.get("official_modified_timezone_known") is True,
        },
        "fetched_at": fetched_at,
        "artifacts": [
            {
                "artifact_id": TFDA_PRIMARY_ARTIFACT_ID,
                "role": "primary",
                "resource_url": discovery["resource_url"],
                "storage_scope": "data_root",
                "data_root_relative_path": artifact_relative,
                "local_artifact_available": True,
                "media_type_verified": "application/zip",
                "bytes": len(payload),
                "sha256": raw_digest,
            }
        ],
        "transform": {"application_build_sha256": application_build_hash, **transform},
        "counts": row_counts,
        "validation": {
            "automated_validation_status": "passed",
            "blocking_errors": [],
            "warnings": list(summary["warnings"]),
        },
        "review": {
            "human_review_status": "approved",
            "required_gates": list(TFDA_SERVING_GATES),
            "completed_gates": list(TFDA_SERVING_GATES),
            "capability_reviews": [
                {
                    "capability": "tfda_ivd_classification",
                    "gate_id": "TFDA-R1-IVD",
                    "status": ivd_review_status,
                }
            ],
        },
        "ivd_coverage": coverage,
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
            "artifact_id": TFDA_PRIMARY_ARTIFACT_ID,
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
                "artifact_id": "tfda-fetch-record",
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
                "artifact_id": "tfda-curated-db",
                "path": db_relative,
                "locator": {"kind": "sqlite_snapshot"},
                "sha256": db_digest,
            },
            {
                "artifact_id": "tfda-validation",
                "path": validation_relative,
                "locator": {"kind": "validation_report"},
                "sha256": validation_digest,
            },
            {
                "artifact_id": "tfda-qualification-candidate",
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
        review_scope: dict[str, Any] = (
            {
                "kind": "owner_review",
                "protocol_section": gate_id,
                "row_count": rows,
                "golden_case_ids": case_ids,
            }
            if official
            else {"kind": "synthetic_fixture", "row_count": rows}
        )
        review = {
            "review_schema_version": 1,
            "gate_id": gate_id,
            "decision": "approved",
            "source_id": TFDA_SOURCE_ID,
            "curated_build_id": build_id,
            "subject_digest": subject_digest,
            "reviewer_id": review_input["reviewer_id"],
            "reviewer_role": review_input["reviewer_role"],
            "identity_assurance": "local_asserted",
            "reviewed_at": review_input["reviewed_at"],
            "protocol_id": protocol_id,
            "protocol_version": protocol_version,
            "protocol_sha256": protocol_sha256,
            "review_scope": review_scope,
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
        "source_id": TFDA_SOURCE_ID,
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
    check_id = f"{TFDA_SOURCE_ID}-check-{build_hash}-g{generation}"
    check_relative = f"checks/{TFDA_SOURCE_ID}/{check_id}.json"
    operational = {
        "latest_seen_version": None,
        "latest_seen_artifact_sha256": raw_digest,
        "latest_candidate_id": None,
        "latest_candidate_status": "none",
        "check_result": "success",
        "failed_stage": None,
        "error_code": None,
        "stale": False,
        "stale_reason_codes": [],
        "freshness_policy_version": "tfda-v1",
        "content_age_status": "unknown",
        "content_age_evidence": None,
    }
    check = {
        "check_schema_version": 1,
        "check_id": check_id,
        "source_id": TFDA_SOURCE_ID,
        "generation": generation,
        "serving_snapshot_id": build_id,
        "serving_curated_build_id": build_id,
        "checked_at": checked_at,
        **operational,
    }
    check_digest = _write_audit_json(data_root / PurePosixPath(check_relative), check)
    descriptor = {
        "descriptor_schema_version": 1,
        "source_id": TFDA_SOURCE_ID,
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
        "ivd_coverage": coverage,
    }


def build_tfda_snapshot(
    payload: bytes,
    data_root: Path,
    *,
    golden_cases: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build and serve a synthetic TFDA snapshot from caller-supplied ZIP bytes.

    Offline and test-only: its reviews are offline-test-builder fixtures, never official
    source qualification. Golden cases only feed the pre-review candidate.
    """

    from ..tfda_source import (
        TFDA_DATASET_ID,
        TFDA_LANDING_URL,
        TFDA_LICENSE,
        TFDA_LICENSE_URL,
        TFDA_PUBLISHER_OID,
        TFDA_SOURCE_IDENTIFIER,
        tfda_raw_revision_id,
    )
    from .nhi import _application_build_identity

    data_root = Path(data_root)
    entry = extract_tfda_csv(payload)
    summary = summarize_tfda_csv(entry)
    registry_bytes = packaged_ivd_registry_bytes()
    decisions = parse_ivd_registry(registry_bytes)
    raw_digest = sha256_bytes(payload)
    discovery = {
        "dataset_id": TFDA_DATASET_ID,
        "identifier": TFDA_SOURCE_IDENTIFIER,
        "publisher_oid": TFDA_PUBLISHER_OID,
        "landing_url": TFDA_LANDING_URL,
        "license_name": TFDA_LICENSE,
        "license_url": TFDA_LICENSE_URL,
        "resource_url": TFDA_RESOURCE_URL,
        "official_modified_at_raw": None,
        "official_modified_timezone_known": False,
    }
    raw_revision_id = tfda_raw_revision_id(
        payload_sha256=raw_digest, payload_size=len(payload), discovery=discovery
    )
    golden_results = _tfda_golden_results(
        entry.payload,
        golden_cases,
        artifact_id=TFDA_PRIMARY_ARTIFACT_ID,
        raw_artifact_sha256=raw_digest,
        transform=_tfda_transform(registry_bytes),
        decisions=decisions,
    )
    failed = [r["golden_case"]["case_id"] for r in golden_results if r["failure_codes"]]
    if failed:
        raise TFDAImportError("GOLDEN_CASE_FAILED", ", ".join(failed))
    artifact_relative = f"raw/{TFDA_SOURCE_ID}/{raw_revision_id}/artifacts/source.zip"
    raw_path = data_root / PurePosixPath(artifact_relative)
    if raw_path.exists():
        if raw_path.read_bytes() != payload:
            raise TFDAImportError("IMMUTABLE_RAW_CONFLICT")
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
        for gate_id in TFDA_SERVING_GATES
    ]
    return _publish_tfda_build(
        data_root,
        payload=payload,
        csv_payload=entry.payload,
        summary=summary,
        raw_revision_id=raw_revision_id,
        artifact_relative=artifact_relative,
        fetch_relative=None,
        discovery=discovery,
        fetched_at=fetched_at,
        application_build_hash=_application_build_identity()[1],
        registry_bytes=registry_bytes,
        decisions=decisions,
        golden_results=golden_results,
        review_inputs=review_inputs,
        protocol=(
            "tfda-r1-synthetic-fixture",
            "1",
            sha256_json({"protocol_id": "tfda-r1-synthetic-fixture", "protocol_version": "1"}),
        ),
        publisher_actor_id="offline-test-builder",
        evidence_inputs=(),
        official=False,
    )


def _review_protocol(protocol_id: str, protocol_version: str) -> tuple[str, str, str, str, str]:
    """Return protocol id, version, SHA-256 and the reviewer id and role it names."""

    if (protocol_id, protocol_version) not in _DELEGATED_REVIEW_PROTOCOLS:
        raise TFDAImportError("REVIEW_PROTOCOL_INVALID")
    try:
        payload = (
            files("taiwan_lab_mcp")
            .joinpath("review_protocols", protocol_id, f"{protocol_version}.json")
            .read_bytes()
        )
        document = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise TFDAImportError("REVIEW_PROTOCOL_INVALID") from exc
    if (
        not isinstance(document, dict)
        or document.get("protocol_id") != protocol_id
        or document.get("protocol_version") != protocol_version
        or document.get("status") != "owner_delegated"
        or sorted(document.get("gates", {})) != sorted(TFDA_SERVING_GATES)
        or not isinstance(document.get("reviewer_id"), str)
        or not document["reviewer_id"]
        or not isinstance(document.get("reviewer_role"), str)
        or not document["reviewer_role"]
    ):
        raise TFDAImportError("REVIEW_PROTOCOL_INVALID")
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
    """Read one fetched raw revision and prove its bytes still match fetch.json."""

    from ..tfda_source import tfda_raw_revision_id

    if not isinstance(raw_revision_id, str) or not _HEX64_RE.fullmatch(raw_revision_id):
        raise TFDAImportError("RAW_REVISION_INTEGRITY", "raw revision id is invalid")
    revision_dir = PurePosixPath("raw", TFDA_SOURCE_ID, raw_revision_id)
    artifact_relative = str(revision_dir / "artifacts" / "source.zip")
    fetch_relative = str(revision_dir / "fetch.json")
    try:
        payload = (data_root / PurePosixPath(artifact_relative)).read_bytes()
        fetch_bytes = (data_root / PurePosixPath(fetch_relative)).read_bytes()
        fetch_record = json.loads(fetch_bytes.decode("utf-8"))
        artifact = fetch_record["artifact"]
        discovery = fetch_record["discovery"]
        recomputed = tfda_raw_revision_id(
            payload_sha256=sha256_bytes(payload), payload_size=len(payload), discovery=discovery
        )
    except (KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, AttributeError) as exc:
        raise TFDAImportError("RAW_REVISION_INTEGRITY", "raw revision is unreadable") from exc
    required_discovery = (
        "dataset_id",
        "identifier",
        "landing_url",
        "resource_url",
        "license_name",
        "license_url",
    )
    if (
        canonical_json_bytes(fetch_record) != fetch_bytes
        or fetch_record.get("fetch_record_schema_version") != 1
        or fetch_record.get("source_id") != TFDA_SOURCE_ID
        or fetch_record.get("raw_revision_id") != raw_revision_id
        or not isinstance(artifact, dict)
        or artifact.get("data_root_relative_path") != artifact_relative
        or artifact.get("sha256") != sha256_bytes(payload)
        or artifact.get("bytes") != len(payload)
        or artifact.get("media_type_verified") != "application/zip"
        or not isinstance(artifact.get("fetched_at"), str)
        or recomputed != raw_revision_id
        or any(
            not isinstance(discovery.get(key), str) or not discovery[key]
            for key in required_discovery
        )
    ):
        raise TFDAImportError("RAW_REVISION_INTEGRITY", "raw revision does not match fetch record")
    return payload, fetch_record, artifact_relative, fetch_relative


def _validated_owner_reviews(owner_reviews: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    reviews = [dict(review) for review in owner_reviews]
    if [review.get("gate_id") for review in reviews] != list(TFDA_SERVING_GATES):
        raise TFDAImportError("OWNER_REVIEW_GATES_INVALID")
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
            raise TFDAImportError("OWNER_REVIEW_SCHEMA_INVALID", str(review.get("gate_id")))
        try:
            reviewed_at = datetime.fromisoformat(str(review["reviewed_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise TFDAImportError("OWNER_REVIEW_SCHEMA_INVALID", review["gate_id"]) from exc
        if reviewed_at.utcoffset() is None:
            raise TFDAImportError("OWNER_REVIEW_SCHEMA_INVALID", review["gate_id"])
        if counts["critical"] or counts["major"]:
            raise TFDAImportError("OWNER_REVIEW_REJECTED", review["gate_id"])
    return reviews


def build_official_tfda_snapshot(
    data_root: Path,
    *,
    raw_revision_id: str,
    approved_golden_cases: Sequence[Mapping[str, Any]],
    owner_reviews: Sequence[Mapping[str, Any]],
    publisher_actor_id: str,
    evidence_files: Sequence[Mapping[str, Any]] = (),
    review_protocol: tuple[str, str] = (TFDA_REVIEW_PROTOCOL_ID, TFDA_REVIEW_PROTOCOL_VERSION),
    pre_publish_check: Callable[[Path], tuple[str, str, bytes]] | None = None,
) -> dict[str, Any]:
    """Build and publish an owner-reviewed TFDA snapshot from a fetched raw revision.

    Every precondition is checked before the first curated write: raw bytes still match
    fetch.json, the application runs from an installed distribution, the owner review
    protocol is approved, all serving gates have owner reviews without critical or major
    findings, and at least ten approved official golden cases pass against the raw ZIP.
    """

    from .nhi import _application_build_identity

    data_root = Path(data_root)
    payload, fetch_record, artifact_relative, fetch_relative = _load_official_raw_revision(
        data_root, raw_revision_id
    )
    identity_kind, application_build_hash = _application_build_identity()
    if identity_kind != "distribution":
        raise TFDAImportError("APPLICATION_BUILD_IDENTITY_MISSING")
    if not isinstance(publisher_actor_id, str) or not publisher_actor_id.strip():
        raise TFDAImportError("PUBLISHER_ACTOR_INVALID")
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
            raise TFDAImportError("EVIDENCE_FILE_INVALID")
        try:
            evidence_inputs.append((artifact_id, name, Path(str(item["path"])).read_bytes()))
        except OSError as exc:
            raise TFDAImportError("EVIDENCE_FILE_INVALID", artifact_id) from exc
    if len({name for _, name, _ in evidence_inputs}) != len(evidence_inputs):
        raise TFDAImportError("EVIDENCE_FILE_INVALID", "duplicate evidence file name")
    protocol_id, protocol_version, protocol_sha256, reviewer_id, reviewer_role = _review_protocol(
        *review_protocol
    )
    # The review is delegated to the reviewer the protocol names; nobody else may sign it.
    for review in review_inputs:
        if (review["reviewer_id"], review["reviewer_role"]) != (reviewer_id, reviewer_role):
            raise TFDAImportError("OWNER_REVIEW_REVIEWER_MISMATCH", review["gate_id"])

    entry = extract_tfda_csv(payload)
    summary = summarize_tfda_csv(entry)
    registry_bytes = packaged_ivd_registry_bytes()
    decisions = parse_ivd_registry(registry_bytes)
    golden_results = _tfda_golden_results(
        entry.payload,
        approved_golden_cases,
        artifact_id=TFDA_PRIMARY_ARTIFACT_ID,
        raw_artifact_sha256=sha256_bytes(payload),
        transform=_tfda_transform(registry_bytes),
        decisions=decisions,
    )
    failed = [r["golden_case"]["case_id"] for r in golden_results if r["failure_codes"]]
    if failed:
        raise TFDAImportError("GOLDEN_CASE_FAILED", ", ".join(failed))
    if len(golden_results) < _MINIMUM_OFFICIAL_GOLDEN_CASES:
        raise TFDAImportError("GOLDEN_CASES_INSUFFICIENT")
    for result in golden_results:
        case = result["golden_case"]
        if (
            case["review_status"] != "approved"
            or case["official_source"] is not True
            or case["evidence_data_root_relative_path"] != artifact_relative
            or case["reviewer_id"] != reviewer_id
        ):
            raise TFDAImportError("GOLDEN_CASE_NOT_APPROVED", case["case_id"])
    return _publish_tfda_build(
        data_root,
        payload=payload,
        csv_payload=entry.payload,
        summary=summary,
        raw_revision_id=raw_revision_id,
        artifact_relative=artifact_relative,
        fetch_relative=fetch_relative,
        discovery=fetch_record["discovery"],
        fetched_at=fetch_record["artifact"]["fetched_at"],
        application_build_hash=application_build_hash,
        registry_bytes=registry_bytes,
        decisions=decisions,
        golden_results=golden_results,
        review_inputs=review_inputs,
        protocol=(protocol_id, protocol_version, protocol_sha256),
        publisher_actor_id=publisher_actor_id,
        evidence_inputs=evidence_inputs,
        official=True,
        pre_publish_check=pre_publish_check,
    )
