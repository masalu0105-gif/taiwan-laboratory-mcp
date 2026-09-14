"""TFDA medical device permit CSV-in-ZIP: archive safety, strict 34-column parse, report.

This first slice is offline only. It reads caller-supplied ZIP bytes, never fetches, never
keeps raw revisions and never builds or publishes a curated snapshot (SDD 10.2).
"""

from __future__ import annotations

import codecs
import csv
import io
import re
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

from ..canonical import canonical_json_bytes, sha256_bytes
from ..util import search_normalize

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
