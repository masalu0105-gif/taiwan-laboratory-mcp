"""CDC recognized laboratory roster (ODS): archive safety, merge semantics, strict 12 raw fields.

SDD 10.4 (SDD-ODS-01). Reads caller-supplied ODS bytes with the standard library only and
never fetches. Vertical merges are rebuilt only from declared ``number-rows-spanned`` anchors
and ``covered-table-cell`` markers, so a real blank cell stays blank. Only the first 12 columns
are materialized; a value beyond them is schema drift.
"""

from __future__ import annotations

import io
import re
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from xml.etree import ElementTree as ET

from ..canonical import canonical_json_bytes, sha256_bytes

CDC_LABS_SOURCE_ID = "cdc_authorized_labs"
CDC_LABS_COLUMNS = (
    "證號",
    "縣市別",
    "機構名稱",
    "部門別",
    "疾病代碼",
    "疾病名稱",
    "檢驗目的",
    "檢驗方法",
    "住址",
    "連絡電話",
    "結束時間",
    "最近一次年度能力試驗審查",
)
CDC_LABS_FIELD_NAMES = (
    "certificate_no",
    "city",
    "institution",
    "department",
    "disease_code",
    "disease_name",
    "purpose",
    "method",
    "address",
    "phone",
    "end_time",
    "latest_annual_pt_review_raw",
)
CDC_LABS_PARSER_VERSION = "cdc-ods-v1"
CDC_LABS_SCHEMA_VERSION = "cdc-labs-12-v1"
ODS_MIMETYPE = b"application/vnd.oasis.opendocument.spreadsheet"
PT_REVIEW_NOT_REQUIRED = "無需能力試驗"
MIB = 1024 * 1024

_WIDTH = len(CDC_LABS_COLUMNS)
_REQUIRED_FIELDS = (
    "certificate_no",
    "city",
    "institution",
    "disease_code",
    "disease_name",
    "purpose",
    "method",
    "end_time",
)
_REQUIRED_INDEXES = tuple(CDC_LABS_FIELD_NAMES.index(name) for name in _REQUIRED_FIELDS)
_END_TIME_INDEX = CDC_LABS_FIELD_NAMES.index("end_time")
_PT_REVIEW_INDEX = CDC_LABS_FIELD_NAMES.index("latest_annual_pt_review_raw")
_LOGICAL_KEY_INDEXES = tuple(
    CDC_LABS_FIELD_NAMES.index(name)
    for name in ("certificate_no", "disease_code", "purpose", "method")
)
# A title row may precede the header; more than this many preamble rows is drift.
_MAX_PREAMBLE_ROWS = 3
_DATE_RE = re.compile(r"^([0-9]{4})/([0-9]{2})/([0-9]{2})$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_SYMLINK_MODE = 0o120000
_T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_X = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_DC_DATE_RE = re.compile(rb"<dc:date>([^<]{1,64})</dc:date>")


@dataclass(frozen=True)
class OdsLimits:
    """SDD 10.4 hard resource budget; every value is counted from actual streamed content."""

    max_archive_bytes: int = 16 * MIB
    max_entries: int = 64
    max_entry_bytes: int = 32 * MIB
    max_total_uncompressed_bytes: int = 64 * MIB
    max_compression_ratio: int = 100
    max_content_bytes: int = 32 * MIB
    max_rows: int = 100_000
    max_elements: int = 2_000_000
    max_depth: int = 64
    max_cell_text_bytes: int = 65_536
    max_total_text_bytes: int = 32 * MIB
    max_row_repeat: int = 10_000
    max_column_repeat: int = 16_384


DEFAULT_ODS_LIMITS = OdsLimits()


class CdcOdsImportError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}{(': ' + detail) if detail else ''}")


def _over(limit: str) -> CdcOdsImportError:
    return CdcOdsImportError("ODS_RESOURCE_LIMIT", limit)


@dataclass(frozen=True)
class CdcLabRow:
    expanded_row_number: int
    source_row_sha256: str
    values: tuple[str, ...]

    def fields(self) -> dict[str, str]:
        return dict(zip(CDC_LABS_FIELD_NAMES, self.values))


@dataclass(frozen=True)
class CdcLabsParseResult:
    sheet_name: str
    rows: tuple[CdcLabRow, ...]
    summary: dict[str, Any]


def _unsafe_entry(info: zipfile.ZipInfo) -> bool:
    name = info.filename.replace("\\", "/")
    return (
        name.startswith("/")
        or bool(_DRIVE_RE.match(name))
        or any(part in {"", ".", ".."} for part in name.split("/"))
        or bool(info.flag_bits & 0x1)
        or (info.external_attr >> 16) & 0o170000 == _SYMLINK_MODE
    )


def _read_archive(payload: bytes, limits: OdsLimits) -> tuple[bytes, bytes | None]:
    if len(payload) > limits.max_archive_bytes:
        raise _over("max_archive_bytes")
    if not payload.startswith(b"PK\x03\x04"):
        raise CdcOdsImportError("ODS_NOT_ZIP")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise CdcOdsImportError("ODS_NOT_ZIP") from exc
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if len(infos) > limits.max_entries:
        raise _over("max_entries")
    by_name: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        if _unsafe_entry(info) or info.filename in by_name:
            raise CdcOdsImportError("ODS_ARCHIVE_PATH_INVALID", info.filename)
        by_name[info.filename] = info
    streamed_total = 0

    def read(name: str) -> bytes | None:
        nonlocal streamed_total
        info = by_name.get(name)
        if info is None:
            return None
        chunks = []
        size = 0
        with archive.open(info) as stream:
            while chunk := stream.read(MIB):
                size += len(chunk)
                streamed_total += len(chunk)
                if size > limits.max_entry_bytes:
                    raise _over("max_entry_bytes")
                if streamed_total > limits.max_total_uncompressed_bytes:
                    raise _over("max_total_uncompressed_bytes")
                if size > limits.max_compression_ratio * max(info.compress_size, 1):
                    raise _over("max_compression_ratio")
                if name == "content.xml" and size > limits.max_content_bytes:
                    raise _over("max_content_bytes")
                chunks.append(chunk)
        return b"".join(chunks)

    try:
        mimetype = read("mimetype")
        if mimetype != ODS_MIMETYPE:
            raise CdcOdsImportError("ODS_MIMETYPE_MISMATCH")
        content = read("content.xml")
        meta = read("meta.xml")
    except CdcOdsImportError:
        raise
    except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError) as exc:
        raise CdcOdsImportError("ODS_ARCHIVE_CORRUPT") from exc
    if content is None:
        raise CdcOdsImportError("ODS_CONTENT_MISSING")
    return content, meta


def _inline_text(node: ET.Element) -> str:
    parts = [node.text or ""]
    for child in node:
        if child.tag == _X + "s":
            try:
                count = int(child.get(_X + "c", "1"))
            except ValueError as exc:
                raise CdcOdsImportError("ODS_XML_INVALID", "text:s count") from exc
            # Refuse before allocating; the per-cell budget is checked again on the text.
            if count > DEFAULT_ODS_LIMITS.max_cell_text_bytes:
                raise _over("max_cell_text_bytes")
            parts.append(" " * max(count, 0))
        elif child.tag == _X + "tab":
            parts.append("\t")
        elif child.tag == _X + "line-break":
            parts.append("\n")
        else:
            parts.append(_inline_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _positive_int(element: ET.Element, attribute: str) -> int:
    raw = element.get(_T + attribute, "1")
    if not raw.isdigit() or int(raw) < 1:
        raise CdcOdsImportError("ODS_XML_INVALID", attribute)
    return int(raw)


@dataclass
class _Sheet:
    name: str
    row_number: int = 0
    header_found: bool = False
    preamble_rows: int = 0
    title_raw: str | None = None
    non_empty: bool = False
    active: list[tuple[str, int] | None] = field(default_factory=lambda: [None] * _WIDTH)
    rows: list[CdcLabRow] = field(default_factory=list)
    inherited_cells: int = 0
    skipped_blank_rows: int = 0


def _date_is_valid(value: str) -> bool:
    match = _DATE_RE.fullmatch(value)
    if match is None:
        return False
    try:
        date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return False
    return True


class _Parser:
    def __init__(self, limits: OdsLimits) -> None:
        self.limits = limits
        self.elements = 0
        self.text_bytes = 0
        self.total_rows = 0

    def cells(self, row: ET.Element) -> tuple[list[tuple[bool, str, int, int]], bool]:
        cells: list[tuple[bool, str, int, int]] = []
        extra_value = False
        for cell in row:
            if cell.tag not in {_T + "table-cell", _T + "covered-table-cell"}:
                continue
            repeat = _positive_int(cell, "number-columns-repeated")
            if repeat > self.limits.max_column_repeat:
                raise _over("max_column_repeat")
            covered = cell.tag == _T + "covered-table-cell"
            text = "" if covered else "\n".join(_inline_text(p) for p in cell.findall(_X + "p"))
            size = len(text.encode("utf-8"))
            if size > self.limits.max_cell_text_bytes:
                raise _over("max_cell_text_bytes")
            self.text_bytes += size
            if self.text_bytes > self.limits.max_total_text_bytes:
                raise _over("max_total_text_bytes")
            spans = (
                _positive_int(cell, "number-rows-spanned"),
                _positive_int(cell, "number-columns-spanned"),
            )
            take = min(repeat, _WIDTH - len(cells))
            cells.extend([(covered, text, *spans)] * take)
            if repeat > take and text:
                extra_value = True
        cells.extend([(False, "", 1, 1)] * (_WIDTH - len(cells)))
        return cells, extra_value

    def row(self, sheet: _Sheet, row: ET.Element) -> None:
        repeat = _positive_int(row, "number-rows-repeated")
        cells, extra_value = self.cells(row)
        if extra_value:
            raise CdcOdsImportError(
                "ODS_EXTRA_COLUMN_VALUE", f"{sheet.name} row {sheet.row_number + 1}"
            )
        texts = [text for _, text, _, _ in cells]
        if not any(texts) and not any(covered for covered, _, _, _ in cells):
            # Blank filler, such as the official roster's final row repeated 1,044,990 times.
            if any(state and state[1] > 0 for state in sheet.active):
                raise CdcOdsImportError("ODS_MERGE_SPAN_CONFLICT", f"{sheet.name} blank row")
            sheet.skipped_blank_rows += repeat
            sheet.row_number += repeat
            return
        sheet.non_empty = True
        if repeat > self.limits.max_row_repeat:
            raise _over("max_row_repeat")
        first_row_number = sheet.row_number + 1
        sheet.row_number += repeat
        if not sheet.header_found:
            if tuple(texts) == CDC_LABS_COLUMNS:
                sheet.header_found = True
                return
            if sum(1 for text in texts if text) <= 1 and sheet.preamble_rows < _MAX_PREAMBLE_ROWS:
                sheet.preamble_rows += 1
                if sheet.title_raw is None:
                    sheet.title_raw = next((text for text in texts if text), None)
                return
            raise CdcOdsImportError("ODS_HEADER_MISMATCH", sheet.name)

        if repeat > 1 and any(covered or rows > 1 for covered, _, rows, _ in cells):
            raise CdcOdsImportError("ODS_MERGE_SPAN_CONFLICT", f"row {first_row_number}")
        values: list[str] = []
        for column, (covered, text, rows_spanned, columns_spanned) in enumerate(cells):
            state = sheet.active[column]
            if columns_spanned > 1:
                raise CdcOdsImportError("ODS_MERGE_SPAN_CONFLICT", f"row {first_row_number}")
            if covered:
                if state is None or state[1] <= 0:
                    raise CdcOdsImportError(
                        "ODS_COVERED_CELL_WITHOUT_ANCHOR", f"row {first_row_number}"
                    )
                values.append(state[0])
                sheet.active[column] = (state[0], state[1] - 1)
                sheet.inherited_cells += 1
            else:
                if state is not None and state[1] > 0:
                    raise CdcOdsImportError("ODS_MERGE_SPAN_CONFLICT", f"row {first_row_number}")
                values.append(text)
                sheet.active[column] = (text, rows_spanned - 1)
        if any(not values[index] for index in _REQUIRED_INDEXES):
            raise CdcOdsImportError("ODS_REQUIRED_VALUE_MISSING", f"row {first_row_number}")
        if not _date_is_valid(values[_END_TIME_INDEX]):
            raise CdcOdsImportError("ODS_END_DATE_INVALID", f"row {first_row_number}")
        self.total_rows += repeat
        if self.total_rows > self.limits.max_rows:
            raise _over("max_rows")
        row_hash = sha256_bytes(canonical_json_bytes(values))
        for offset in range(repeat):
            sheet.rows.append(CdcLabRow(first_row_number + offset, row_hash, tuple(values)))

    def parse(self, content: bytes) -> list[_Sheet]:
        if b"<!DOCTYPE" in content or b"<!ENTITY" in content:
            raise CdcOdsImportError("ODS_XML_FORBIDDEN_DECLARATION")
        sheets: list[_Sheet] = []
        current: _Sheet | None = None
        depth = 0
        try:
            for event, element in ET.iterparse(io.BytesIO(content), events=("start", "end")):
                if event == "start":
                    depth += 1
                    self.elements += 1
                    if depth > self.limits.max_depth:
                        raise _over("max_depth")
                    if self.elements > self.limits.max_elements:
                        raise _over("max_elements")
                    if element.tag == _T + "table":
                        current = _Sheet(element.get(_T + "name") or "")
                        sheets.append(current)
                    continue
                depth -= 1
                if element.tag == _T + "table-row" and current is not None:
                    self.row(current, element)
                    element.clear()
                elif element.tag == _T + "table":
                    current = None
                    element.clear()
        except ET.ParseError as exc:
            raise CdcOdsImportError("ODS_XML_INVALID") from exc
        return sheets


def _pt_review_kind(value: str) -> str:
    if value == "":
        return "blank"
    if value == PT_REVIEW_NOT_REQUIRED:
        return "not_required"
    return "date" if _date_is_valid(value) else "other"


def parse_cdc_labs_ods(
    payload: bytes, *, limits: OdsLimits = DEFAULT_ODS_LIMITS
) -> CdcLabsParseResult:
    """Parse the one roster sheet into method-level rows with raw values and row locators."""

    if not isinstance(payload, bytes):
        raise CdcOdsImportError("ODS_NOT_ZIP")
    content, meta = _read_archive(payload, limits)
    parser = _Parser(limits)
    sheets = parser.parse(content)
    rosters = [sheet for sheet in sheets if sheet.non_empty]
    if not rosters:
        raise CdcOdsImportError("ODS_SHEET_MISSING")
    if len(rosters) > 1:
        raise CdcOdsImportError("ODS_SHEET_AMBIGUOUS", ",".join(sheet.name for sheet in rosters))
    roster = rosters[0]
    if not roster.header_found:
        raise CdcOdsImportError("ODS_HEADER_MISMATCH", roster.name)
    if not roster.rows:
        raise CdcOdsImportError("ODS_NO_DATA_ROWS", roster.name)
    logical_keys = Counter(
        tuple(item.values[index] for index in _LOGICAL_KEY_INDEXES) for item in roster.rows
    )
    pt_kinds = Counter(_pt_review_kind(item.values[_PT_REVIEW_INDEX]) for item in roster.rows)
    meta_date = _DC_DATE_RE.search(meta) if meta else None
    summary = {
        "parser_version": CDC_LABS_PARSER_VERSION,
        "schema_version": CDC_LABS_SCHEMA_VERSION,
        "sheet_name": roster.name,
        "title_raw": roster.title_raw,
        "rows": len(roster.rows),
        "distinct_certificates": len({item.values[0] for item in roster.rows}),
        "distinct_diseases": len({(item.values[4], item.values[5]) for item in roster.rows}),
        "duplicate_logical_keys": sum(1 for count in logical_keys.values() if count > 1),
        "pt_review_kinds": {
            kind: pt_kinds.get(kind, 0) for kind in ("date", "not_required", "blank", "other")
        },
        "inherited_cells": roster.inherited_cells,
        "skipped_blank_rows": roster.skipped_blank_rows,
        "ignored_sheets": [sheet.name for sheet in sheets if not sheet.non_empty],
        "content_xml_bytes": len(content),
        "xml_elements": parser.elements,
        "cell_text_bytes": parser.text_bytes,
        "meta_date_raw": meta_date.group(1).decode("utf-8", "replace") if meta_date else None,
    }
    return CdcLabsParseResult(roster.name, tuple(roster.rows), summary)
