"""CDC specimen collection manual chapter 2: rebuild table rows from a normalized page layout.

ADR 0003 (engineering decision 2026-09-15). The input is CdcLayoutV1: per page, ruling segments
with their colour, characters with boxes in PDF stream order, optional marked-content boxes and
the Word table tags (each TR lists its children as absent, or as marked content ids). Columns
come from the header text; row boundaries only from black lines that reach both column rules; a
merged cell repeats its text in every row it covers; text that overflows onto the next page joins
the cell it continues. A layout these rules cannot read safely raises instead of guessing.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from ..canonical import canonical_json_bytes, sha256_bytes

CDC_MANUAL_LAYOUT_RULES_VERSION = "cdc-manual-layout-v1"
CDC_SPECIMEN_FIELDS = (
    "disease",
    "specimen",
    "purpose",
    "collection_time",
    "volume_requirement",
    "transport_method",
    "retention_raw",
    "notes",
)
_HEADERS = {
    "傳染病名稱": "disease",
    "採檢項目": "specimen",
    "採檢目的": "purpose",
    "採檢時間": "collection_time",
    "採檢量及規定": "volume_requirement",
    "送驗方式": "transport_method",
    "應保存種類(應保存時間)": "retention_raw",
    "注意事項": "notes",
}
_EIGHT_COLUMNS = CDC_SPECIMEN_FIELDS
_SEVEN_COLUMNS = tuple(name for name in CDC_SPECIMEN_FIELDS if name != "retention_raw")
# A row ends where one of these columns has a boundary; other columns may be merged cells.
_KEY_FIELDS = frozenset({"disease", "specimen", "purpose", "collection_time", "volume_requirement"})
_RULE_END_TOLERANCE = 0.5
_WIDTH_TOLERANCE = 1.0
_COLUMN_RULE_MIN_HEIGHT = 25.0
_CLUSTER_GAP = 2.0
_SECTION_RE = re.compile(r"^2\.([1-9][0-9]*)\.?(\D.*)$")
_PRINTED_PAGE_RE = re.compile(r"頁碼:第([0-9]+)頁")


class CdcManualLayoutError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}{(': ' + detail) if detail else ''}")


@dataclass(frozen=True)
class CdcSpecimenRow:
    values: tuple[str | None, ...]
    locator: dict[str, Any]
    source_row_sha256: str

    def fields(self) -> dict[str, str | None]:
        return dict(zip(CDC_SPECIMEN_FIELDS, self.values))


@dataclass(frozen=True)
class CdcSpecimenLayoutResult:
    rows: list[CdcSpecimenRow]
    summary: dict[str, Any]


def _squeeze(text: str) -> str:
    return unicodedata.normalize("NFKC", "".join(text.split()))


def _cluster(values: list[float], gap: float = _CLUSTER_GAP) -> list[float]:
    groups: list[list[float]] = []
    for value in sorted(values):
        if groups and value - groups[-1][-1] <= gap:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [sum(group) / len(group) for group in groups]


def _is_black(color: Any) -> bool:
    return (
        isinstance(color, list)
        and len(color) >= 3
        and all(isinstance(value, (int, float)) for value in color[:3])
        and max(color[:3]) <= 64
    )


class _Group:
    def __init__(self, cell: _Cell) -> None:
        self.cells = [cell]

    def text(self) -> str:
        return "\n".join(text for text in (cell.own_text() for cell in self.cells) if text)


@dataclass(eq=False)
class _Cell:
    chars: list[tuple[str, tuple[float, float, float, float] | None]] = field(default_factory=list)
    group: _Group | None = None

    def own_text(self) -> str:
        parts: list[str] = []
        previous = None
        for text, box in self.chars:
            if box is not None:
                if previous is not None and box[0] < previous[0] - 1 and box[1] > previous[1] + 3:
                    parts.append("\n")
                previous = box
            parts.append(text)
        lines = (line.strip() for line in "".join(parts).split("\n"))
        return "\n".join(line for line in lines if line)

    def has_text(self) -> bool:
        return any(text.strip() for text, _ in self.chars)


def _link(earlier: _Cell, later: _Cell) -> None:
    """Make both cells one merged cell whose text reads the earlier page first."""

    assert earlier.group is not None and later.group is not None
    if earlier.group is later.group:
        return
    moved = later.group
    earlier.group.cells.extend(moved.cells)
    for cell in moved.cells:
        cell.group = earlier.group


@dataclass
class _PageTable:
    number: int
    printed_page: int | None
    section: str | None
    xs: list[float]
    columns: list[list[float]]
    cells: dict[tuple[int, int], _Cell]
    has_text: bool
    header_bottom: float | None
    names: tuple[str, ...] | None
    table_rows: list[list[Any]]
    mcid_columns: dict[int, set[int]]
    mcid_text: dict[int, str]

    @property
    def widths(self) -> list[float]:
        return [right - left for left, right in zip(self.xs, self.xs[1:])]

    @property
    def body_top(self) -> float:
        if self.header_bottom is not None:
            return self.header_bottom
        return min(ys[0] for ys in self.columns if ys)

    def cell_index_at(self, col: int, y: float) -> int | None:
        ys = self.columns[col]
        return next((k for k in range(len(ys) - 1) if ys[k] <= y < ys[k + 1]), None)

    def top_cell(self, col: int) -> _Cell | None:
        ys = self.columns[col]
        index = next((k for k in range(len(ys) - 1) if ys[k] >= self.body_top - 1), None)
        return None if index is None else self.cells[(col, index)]

    def last_cell(self, col: int) -> _Cell | None:
        ys = self.columns[col]
        return self.cells[(col, len(ys) - 2)] if len(ys) >= 2 else None


def _read_page(page: dict[str, Any]) -> _PageTable | None:
    segments = page["segments"]
    chars = page["chars"]
    verticals = [
        (s["x0"] + s["x1"]) / 2
        for s in segments
        if _is_black(s.get("color"))
        and s["x1"] - s["x0"] < 3
        and s["y1"] - s["y0"] > _COLUMN_RULE_MIN_HEIGHT
    ]
    xs = _cluster(verticals)
    if len(xs) < 2:
        return None
    columns = []
    for left, right in zip(xs, xs[1:]):
        columns.append(
            _cluster(
                [
                    (s["y0"] + s["y1"]) / 2
                    for s in segments
                    if _is_black(s.get("color"))
                    and s["y1"] - s["y0"] < 3
                    and s["x1"] - s["x0"] > 3
                    and s["x0"] <= left + _RULE_END_TOLERANCE
                    and s["x1"] >= right - _RULE_END_TOLERANCE
                ]
            )
        )
    cells = {
        (col, k): _Cell() for col, ys in enumerate(columns) for k in range(max(len(ys) - 1, 0))
    }
    for cell in cells.values():
        cell.group = _Group(cell)
    outside: list[tuple[str, float, float]] = []
    mcid_columns: dict[int, set[int]] = {}
    mcid_text: dict[int, list[str]] = {}
    last_cell = None
    for char in chars:
        text = char["text"]
        box = (char["x0"], char["y0"], char["x1"], char["y1"])
        mcid = char.get("mcid")
        if mcid is not None:
            mcid_text.setdefault(mcid, []).append(text)
        if box[2] - box[0] < 0.5:
            # A generated space has no real box; it belongs to the previous character's cell.
            if last_cell is not None:
                last_cell.chars.append((text, None))
            continue
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        col = next((i for i in range(len(xs) - 1) if xs[i] <= cx < xs[i + 1]), None)
        index = (
            None
            if col is None
            else next(
                (
                    k
                    for k in range(len(columns[col]) - 1)
                    if columns[col][k] <= cy < columns[col][k + 1]
                ),
                None,
            )
        )
        if col is None or index is None:
            last_cell = None
            outside.append((text, box[0], box[1]))
            continue
        last_cell = cells[(col, index)]
        last_cell.chars.append((text, box))
        if mcid is not None:
            mcid_columns.setdefault(mcid, set()).add(col)
    for item in page.get("marked_content", ()):
        # Marked content without visible characters (an empty own cell) still has a position.
        if item["mcid"] not in mcid_columns:
            cx = (item["x0"] + item["x1"]) / 2
            col = next((i for i in range(len(xs) - 1) if xs[i] <= cx < xs[i + 1]), None)
            if col is not None:
                mcid_columns[item["mcid"]] = {col}

    table_top = min((ys[0] for ys in columns if ys), default=0.0)
    lines: list[list[Any]] = []
    for text, x0, y0 in outside:
        if y0 >= table_top:
            continue
        if lines and abs(y0 - lines[-1][0]) <= 3:
            lines[-1][1].append(text)
        else:
            lines.append([y0, [text]])
    section = None
    for _, parts in lines:
        match = _SECTION_RE.fullmatch("".join("".join(parts).split()))
        if match:
            section = f"2.{match.group(1)} {match.group(2)}"
    printed = _PRINTED_PAGE_RE.search(_squeeze("".join(char["text"] for char in chars)))

    header_bottom = None
    names = None
    first_column = columns[0]
    for k in range(len(first_column) - 1):
        if _squeeze(cells[(0, k)].own_text()) == "傳染病名稱":
            header_bottom = first_column[k + 1]
            middle = (first_column[k] + first_column[k + 1]) / 2
            found = []
            for col in range(len(columns)):
                index = next(
                    (
                        i
                        for i in range(len(columns[col]) - 1)
                        if columns[col][i] <= middle < columns[col][i + 1]
                    ),
                    None,
                )
                header = "" if index is None else _squeeze(cells[(col, index)].own_text())
                found.append(_HEADERS.get(header))
            names = tuple(found)  # type: ignore[arg-type]
            if names not in (_EIGHT_COLUMNS, _SEVEN_COLUMNS):
                raise CdcManualLayoutError("LAYOUT_HEADER_MISMATCH", f"page {page['page_number']}")
            break
    return _PageTable(
        number=int(page["page_number"]),
        printed_page=int(printed.group(1)) if printed else None,
        section=section,
        xs=xs,
        columns=columns,
        cells=cells,
        has_text=bool(chars),
        header_bottom=header_bottom,
        names=names,
        table_rows=page.get("table_rows") or [],
        mcid_columns=mcid_columns,
        mcid_text={key: "".join(value) for key, value in mcid_text.items()},
    )


def _child_column(table: _PageTable, child: list[int]) -> int | None:
    columns = set().union(*(table.mcid_columns.get(mcid, set()) for mcid in child))
    if len(columns) > 1:
        raise CdcManualLayoutError("LAYOUT_TAG_COLUMN_AMBIGUOUS", f"page {table.number}")
    return next(iter(columns), None)


def _child_has_text(table: _PageTable, child: list[int]) -> bool:
    return any(table.mcid_text.get(mcid, "").strip() for mcid in child)


def _split_row(table: _PageTable, children: list[Any]) -> tuple[list[Any], list[Any]]:
    """Continuation children come first; own children follow in increasing column order."""

    boundary = len(children)
    last_col = None
    for index in range(len(children) - 1, -1, -1):
        child = children[index]
        if child is None:
            break
        col = _child_column(table, child)
        if col is not None:
            if last_col is not None and col >= last_col:
                break
            last_col = col
        boundary = index
    return children[:boundary], children[boundary:]


def _continued_columns(table: _PageTable, children: list[Any]) -> set[int]:
    prefix, own = _split_row(table, children)
    if not prefix:
        return set()
    width = len(table.columns)
    known = {
        col
        for child in prefix
        if child is not None and (col := _child_column(table, child)) is not None
    }
    absent = sum(1 for child in prefix if child is None or _child_column(table, child) is None)
    own_known = {col for child in own if (col := _child_column(table, child)) is not None}
    pool = (
        {
            col
            for col in range(width)
            if (cell := table.top_cell(col)) is not None and not cell.has_text()
        }
        - known
        - own_known
    )
    # Own cells without text or position sit between their neighbouring own columns.
    previous = -1
    unknown = 0
    for child in [*own, None]:
        col = None if child is None else _child_column(table, child)
        if child is not None and col is None:
            unknown += 1
            continue
        upper = width if child is None else col
        if unknown:
            between = {candidate for candidate in pool if previous < candidate < upper}
            if len(between) != unknown:
                raise CdcManualLayoutError("LAYOUT_CONTINUATION_AMBIGUOUS", f"page {table.number}")
            pool -= between
            unknown = 0
        if col is not None:
            previous = col
    if len(pool) != absent:
        raise CdcManualLayoutError("LAYOUT_CONTINUATION_AMBIGUOUS", f"page {table.number}")
    return known | pool


def parse_cdc_specimen_layout(layout: dict[str, Any]) -> CdcSpecimenLayoutResult:
    """Return chapter 2 specimen rows in page order, or raise CdcManualLayoutError."""

    if not isinstance(layout, dict) or layout.get("layout_schema_version") != 1:
        raise CdcManualLayoutError("LAYOUT_SCHEMA_INVALID")
    try:
        pages = sorted(layout["pages"], key=lambda page: int(page["page_number"]))
        tables: list[_PageTable] = []
        for page in pages:
            table = _read_page(page)
            if table is not None and not table.has_text:
                raise CdcManualLayoutError("LAYOUT_NO_TEXT_LAYER", f"page {page['page_number']}")
            if not tables and (table is None or table.names is None):
                continue
            if table is None:
                # Chapter 2 ends at the first page without a table.
                break
            tables.append(table)
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, CdcManualLayoutError):
            raise
        raise CdcManualLayoutError("LAYOUT_SCHEMA_INVALID") from exc
    if not tables:
        raise CdcManualLayoutError("LAYOUT_NO_TABLE")

    section = None
    joins = 0
    continuation_pages = []
    bands: list[tuple[_PageTable, float, float, list[_Cell | None]]] = []
    previous: _PageTable | None = None
    for table in tables:
        if table.names is None:
            assert previous is not None and previous.names is not None
            if len(table.widths) != len(previous.widths) or any(
                abs(a - b) > _WIDTH_TOLERANCE for a, b in zip(table.widths, previous.widths)
            ):
                raise CdcManualLayoutError("LAYOUT_HEADER_MISSING", f"page {table.number}")
            table.names = previous.names
            continuation_pages.append(table.number)
        section = table.section or section
        if section is None:
            raise CdcManualLayoutError("LAYOUT_SECTION_MISSING", f"page {table.number}")
        table.section = section
        width = len(table.columns)
        rows = [row for row in table.table_rows if any(child is not None for child in row)]
        header_rows = [
            index
            for index, row in enumerate(rows)
            if any(
                child is not None
                and _squeeze("".join(table.mcid_text.get(mcid, "") for mcid in child))
                == "傳染病名稱"
                for child in row
            )
        ]
        body = rows[header_rows[-1] + 1 :] if header_rows else rows
        for position, children in enumerate(body):
            if len(children) != width:
                raise CdcManualLayoutError("LAYOUT_TAG_WIDTH_MISMATCH", f"page {table.number}")
            prefix, _ = _split_row(table, children)
            overflow = [
                child for child in prefix if child is not None and _child_has_text(table, child)
            ]
            if position > 0:
                if overflow:
                    raise CdcManualLayoutError("LAYOUT_MID_PAGE_OVERFLOW", f"page {table.number}")
                continue
            if previous is None:
                if prefix:
                    raise CdcManualLayoutError(
                        "LAYOUT_CONTINUATION_AMBIGUOUS", f"page {table.number}"
                    )
                continue
            for col in sorted(_continued_columns(table, children)):
                earlier, later = previous.last_cell(col), table.top_cell(col)
                if earlier is None or later is None:
                    raise CdcManualLayoutError(
                        "LAYOUT_CONTINUATION_AMBIGUOUS", f"page {table.number}"
                    )
                _link(earlier, later)
                joins += 1

        key_columns = [index for index, name in enumerate(table.names) if name in _KEY_FIELDS]
        bounds = _cluster(
            [y for index in key_columns for y in table.columns[index] if y >= table.body_top - 1]
        )
        for top, bottom in zip(bounds, bounds[1:]):
            middle = (top + bottom) / 2
            covering = []
            for col in range(width):
                index = table.cell_index_at(col, middle)
                covering.append(None if index is None else table.cells[(col, index)])
            if any(cell is None for cell in covering):
                raise CdcManualLayoutError("LAYOUT_CELL_MISSING", f"page {table.number}")
            bands.append((table, top, bottom, covering))
        previous = table

    result_rows = []
    for table, top, bottom, covering in bands:
        by_name = {
            name: cell.group.text()  # type: ignore[union-attr]
            for name, cell in zip(table.names or (), covering)
        }
        values = tuple(by_name.get(name) for name in CDC_SPECIMEN_FIELDS)
        if not any(values):
            raise CdcManualLayoutError("LAYOUT_EMPTY_ROW", f"page {table.number}")
        result_rows.append(
            CdcSpecimenRow(
                values=values,
                locator={
                    "locator_type": "cdc_pdf_row",
                    "pdf_page": table.number,
                    "printed_page": table.printed_page,
                    "table_section": table.section,
                    "row_bbox": [
                        round(table.xs[0]),
                        round(top),
                        round(table.xs[-1]),
                        round(bottom),
                    ],
                },
                source_row_sha256=sha256_bytes(canonical_json_bytes(list(values))),
            )
        )
    return CdcSpecimenLayoutResult(
        rows=result_rows,
        summary={
            "rules_version": CDC_MANUAL_LAYOUT_RULES_VERSION,
            "table_pages": [table.number for table in tables],
            "continuation_pages": continuation_pages,
            "page_joins": joins,
            "rows": len(result_rows),
            "eight_column_rows": sum(1 for table, *_ in bands if table.names == _EIGHT_COLUMNS),
            "seven_column_rows": sum(1 for table, *_ in bands if table.names == _SEVEN_COLUMNS),
        },
    )
