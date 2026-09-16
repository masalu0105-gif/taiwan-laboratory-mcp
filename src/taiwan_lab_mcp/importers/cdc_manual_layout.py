"""CDC specimen collection manual: rebuild table rows from a normalized page layout.

Each kind of table the manual prints is one CdcTableSpec: chapter 2 specimen requirements,
chapter 7 testing locations and the chapter 7 receiving-unit contacts. A page belongs to the spec
whose column names its header row matches, so a chapter only ever reads its own tables.

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
CDC_TESTING_LOCATION_FIELDS = (
    "disease",
    "collecting_unit",
    "specimen",
    "method",
    "turnaround_raw",
    "testing_period_raw",
    "receiving_unit",
    "bsl_raw",
    "notes",
)
CDC_RECEIVING_UNIT_FIELDS = ("unit_name", "phone", "fax", "address")


def _section_pattern(chapter: str) -> re.Pattern[str]:
    return re.compile(rf"^({chapter}(?:\.[0-9]+)+)\.?(\D.*)$")


@dataclass(frozen=True)
class CdcTableSpec:
    """One kind of table in the manual: its columns, where a row ends and how sections are named.

    `anchor` is the header text of the first column, `variants` the column orders the manual
    actually prints, and `key_fields` the columns whose boundaries end a row (other columns may
    be merged cells covering several rows).
    """

    name: str
    fields: tuple[str, ...]
    headers: dict[str, str]
    variants: tuple[tuple[str, ...], ...]
    key_fields: frozenset[str]
    section_re: re.Pattern[str]
    anchor: str


CDC_SPECIMEN_SPEC = CdcTableSpec(
    name="cdc_specimen_requirement",
    fields=CDC_SPECIMEN_FIELDS,
    headers={
        "傳染病名稱": "disease",
        "採檢項目": "specimen",
        "採檢目的": "purpose",
        "採檢時間": "collection_time",
        "採檢量及規定": "volume_requirement",
        "送驗方式": "transport_method",
        "應保存種類(應保存時間)": "retention_raw",
        "注意事項": "notes",
    },
    variants=(
        CDC_SPECIMEN_FIELDS,
        tuple(name for name in CDC_SPECIMEN_FIELDS if name != "retention_raw"),
    ),
    key_fields=frozenset(
        {"disease", "specimen", "purpose", "collection_time", "volume_requirement"}
    ),
    section_re=_section_pattern("2"),
    anchor="傳染病名稱",
)
# Chapter 7 (owner 2026-09-16, OD-18). Section 7.7 prints 檢驗期間 instead of 檢驗期限 and has no
# BSL column, so those two official column names stay separate fields.
CDC_TESTING_LOCATION_SPEC = CdcTableSpec(
    name="cdc_testing_location",
    fields=CDC_TESTING_LOCATION_FIELDS,
    headers={
        "傳染病名稱": "disease",
        "採檢單位": "collecting_unit",
        "採檢項目": "specimen",
        "檢驗方法": "method",
        "檢驗期限": "turnaround_raw",
        "檢驗期間": "testing_period_raw",
        "收件單位": "receiving_unit",
        "實驗室生物安全等級(BSL)": "bsl_raw",
        "備註": "notes",
    },
    variants=(
        (
            "disease",
            "collecting_unit",
            "specimen",
            "method",
            "turnaround_raw",
            "receiving_unit",
            "bsl_raw",
            "notes",
        ),
        (
            "disease",
            "collecting_unit",
            "specimen",
            "method",
            "testing_period_raw",
            "receiving_unit",
            "notes",
        ),
    ),
    # Every column ends a row here: on 1150826 page 101 one arrangement differs only by its
    # 檢驗期限 (Sanger 定序 2-7 工作日 against 目標次世代定序 10-15 工作日), and the Word tags
    # count it as its own row.
    key_fields=frozenset(CDC_TESTING_LOCATION_FIELDS),
    section_re=_section_pattern("7"),
    anchor="傳染病名稱",
)
CDC_RECEIVING_UNIT_SPEC = CdcTableSpec(
    name="cdc_receiving_unit",
    fields=CDC_RECEIVING_UNIT_FIELDS,
    headers={"單位名稱": "unit_name", "電話": "phone", "傳真": "fax", "地址": "address"},
    variants=(CDC_RECEIVING_UNIT_FIELDS,),
    key_fields=frozenset(CDC_RECEIVING_UNIT_FIELDS),
    section_re=_section_pattern("7"),
    anchor="單位名稱",
)
_SPECS = (CDC_SPECIMEN_SPEC, CDC_TESTING_LOCATION_SPEC, CDC_RECEIVING_UNIT_SPEC)
CDC_MANUAL_TABLE_NAMES = tuple(spec.name for spec in _SPECS)
_HEADERS = {text: field for spec in _SPECS for text, field in spec.headers.items()}
_ANCHORS = frozenset(spec.anchor for spec in _SPECS)
_RULE_END_TOLERANCE = 0.5
_RULE_JOIN_GAP = 1.0
_WIDTH_TOLERANCE = 1.0
_COLUMN_RULE_MIN_HEIGHT = 25.0
_CLUSTER_GAP = 2.0
_PRINTED_PAGE_RE = re.compile(r"頁碼:第([0-9]+)頁")
# Page header 「版次：1150826 核准日期：115年08月26日」.
_VERSION_RE = re.compile(r"版次:([0-9]{7})")
_APPROVED_DATE_RE = re.compile(r"核准日期:([0-9]+年[0-9]+月[0-9]+日)")
# 「1.」「2、」 start a list item; 「3.4」 and 「2.8.6」 are section numbers.
_LIST_ITEM_RE = re.compile(r"^[0-9]+[\.、](?![0-9])")
# A line wrapped when the room left before the column rule was less than the next line's first
# piece needs plus this much. Word keeps a cell margin of about 5.4 pt and glyph boxes stop at the
# ink. Measured on 1150826: wrapped lines left up to 7.0 pt more (「0 mL 靜脈血，」), lines the
# author ended left 8.0 pt or more (「急性期」); a few 「2-8oC」 lines in between read either way.
_WRAP_ROOM = 7.5
# Word keeps an opening bracket with what follows it and never starts a line with a closing mark.
_OPENING = frozenset("（(「『【〔《〈“‘[")
_CLOSING = frozenset("）)」』】〕》〉”’]，,。.、；;：:！!？?%")


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
    display_values: tuple[str | None, ...] = ()
    field_names: tuple[str, ...] = CDC_SPECIMEN_FIELDS

    def fields(self) -> dict[str, str | None]:
        return dict(zip(self.field_names, self.values))

    def display_fields(self) -> dict[str, str | None]:
        """Cell text for reading: wrapped lines joined, author line breaks and list items kept."""

        return dict(zip(self.field_names, self.display_values))


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


@dataclass(eq=False)
class _Line:
    items: list[tuple[str, tuple[float, float, float, float] | None]] = field(default_factory=list)
    right: float | None = None

    def add(self, text: str, box: tuple[float, float, float, float] | None) -> None:
        self.items.append((text, box))
        if box is not None:
            self.right = box[2] if self.right is None else max(self.right, box[2])

    def text(self) -> str:
        return "".join(text for text, _ in self.items).strip()

    def first_piece_width(self) -> float:
        """Width of the start of the line that Word would move to the next line as one piece."""

        items = self.items
        start = next((index for index, (_, box) in enumerate(items) if box is not None), None)
        if start is None:
            return 0.0

        def boxed(index: int) -> bool:
            # Spaces carry no box; one ends the piece.
            return index < len(items) and items[index][1] is not None

        end = start
        while items[end][0] in _OPENING and boxed(end + 1):
            end += 1
        if items[end][0].isascii() and items[end][0].isalnum():
            # A run of ASCII characters wraps as one word; any other character wraps alone.
            while boxed(end + 1) and items[end + 1][0].isascii():
                end += 1
        while boxed(end + 1) and items[end + 1][0] in _CLOSING:
            end += 1
        first, last = items[start][1], items[end][1]
        assert first is not None and last is not None
        return last[2] - first[0]


class _Group:
    def __init__(self, cell: _Cell) -> None:
        self.cells = [cell]

    def text(self) -> str:
        return "\n".join(text for text in (cell.own_text() for cell in self.cells) if text)

    def display_text(self) -> str:
        """Owner 2026-09-15 chose B: join lines that ran out of room; keep other line breaks."""

        joined = ""
        previous: tuple[_Line, float] | None = None
        for cell in self.cells:
            for line in cell.lines():
                text = line.text()
                if previous is None:
                    joined = text
                elif _LIST_ITEM_RE.match(text):
                    joined += "\n" + text
                elif text[0] in _CLOSING or (
                    previous[0].right is not None
                    and previous[1] - previous[0].right < line.first_piece_width() + _WRAP_ROOM
                ):
                    # The next piece did not fit on the previous line, so the line wrapped.
                    ascii_edge = (
                        joined[-1:].isascii()
                        and joined[-1:].isalnum()
                        and text[:1].isascii()
                        and text[:1].isalnum()
                    )
                    joined += (" " if ascii_edge else "") + text
                else:
                    joined += "\n" + text
                previous = (line, cell.right)
        return joined


@dataclass(eq=False)
class _Cell:
    right: float = 0.0
    chars: list[tuple[str, tuple[float, float, float, float] | None]] = field(default_factory=list)
    group: _Group | None = None

    def lines(self) -> list[_Line]:
        lines: list[_Line] = []
        current: _Line | None = None
        previous = None
        for text, box in self.chars:
            # A line starts where the text moves down and back left, or wholly below the previous
            # character (a one-character line such as 「。」 has nothing to its left).
            starts_new_line = (
                box is not None
                and previous is not None
                and box[1] > previous[1] + 3
                and (box[0] < previous[0] - 1 or box[1] >= previous[3] - 1)
            )
            if current is None or starts_new_line:
                current = _Line()
                lines.append(current)
            current.add(text, box)
            if box is not None:
                previous = box
        return [line for line in lines if line.text()]

    def own_text(self) -> str:
        return "\n".join(line.text() for line in self.lines())

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
    version: str | None
    approved_date_raw: str | None
    # The heading above the table, per table kind: 「2.2 第二類法定傳染病檢體」, 「7.1 第一類法定傳染病」.
    sections: dict[str, str]
    spec: CdcTableSpec | None
    xs: list[float]
    columns: list[list[float]]
    cells: dict[tuple[int, int], _Cell]
    has_text: bool
    header_bottom: float | None
    names: tuple[str, ...] | None
    table_rows: list[list[Any]]
    mcid_columns: dict[int, set[int]]
    mcid_box_columns: dict[int, set[int]]
    mcid_text: dict[int, str]
    # Filled while reading a chapter: the section this page's rows belong to.
    resolved_section: str | None = None

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


def _joined_runs(pieces: list[tuple[float, float]]) -> list[list[float]]:
    """Return the pieces joined where they touch; Word draws one ruling piece per cell."""

    joined: list[list[float]] = []
    for low, high in sorted(pieces):
        if joined and low <= joined[-1][1] + _RULE_JOIN_GAP:
            joined[-1][1] = max(joined[-1][1], high)
        else:
            joined.append([low, high])
    return joined


def _read_page(page: dict[str, Any]) -> _PageTable | None:
    segments = page["segments"]
    chars = page["chars"]
    verticals = [
        s
        for s in segments
        if _is_black(s.get("color"))
        and s["x1"] - s["x0"] < 3
        and s["y1"] - s["y0"] > _COLUMN_RULE_MIN_HEIGHT
    ]
    xs = _cluster([(s["x0"] + s["x1"]) / 2 for s in verticals])
    if len(xs) < 2:
        return None
    # The table spans its column rules; the page header box above has lines too (1150826 manual).
    table_top = min(s["y0"] for s in verticals)
    table_bottom = max(s["y1"] for s in verticals)
    # A column rule is drawn per cell, so a short row's pieces can each be under the minimum
    # height and drop out (1150826 page 121: the 15.6 pt header row of 7.9). The table reaches as
    # far as pieces that touch the columns already found, and no further.
    top, bottom = table_top, table_bottom
    for x in xs:
        for low, high in _joined_runs(
            [
                (s["y0"], s["y1"])
                for s in segments
                if _is_black(s.get("color"))
                and s["x1"] - s["x0"] < 3
                and abs((s["x0"] + s["x1"]) / 2 - x) <= _CLUSTER_GAP
            ]
        ):
            if low <= table_top <= high:
                top = min(top, low)
            if low <= table_bottom <= high:
                bottom = max(bottom, high)
    table_top, table_bottom = top, bottom
    # Word draws a row rule as one piece per cell plus a short piece over each column rule, and a
    # cell's own piece can start beside its column rule (1150826 page 93: 0.6 pt right of it), so
    # the pieces at one height are joined before asking which columns that rule spans.
    horizontals = [
        s
        for s in segments
        if _is_black(s.get("color"))
        and s["y1"] - s["y0"] < 3
        and table_top - 1 <= (s["y0"] + s["y1"]) / 2 <= table_bottom + 1
    ]
    levels = _cluster([(s["y0"] + s["y1"]) / 2 for s in horizontals])
    at_level: list[list[tuple[float, float]]] = [[] for _ in levels]
    for s in horizontals:
        middle = (s["y0"] + s["y1"]) / 2
        at_level[min(range(len(levels)), key=lambda k: abs(levels[k] - middle))].append(
            (s["x0"], s["x1"])
        )
    runs = [_joined_runs(pieces) for pieces in at_level]
    columns = []
    for left, right in zip(xs, xs[1:]):
        columns.append(
            [
                level
                for level, joined in zip(levels, runs)
                if any(
                    x0 <= left + _RULE_END_TOLERANCE and x1 >= right - _RULE_END_TOLERANCE
                    for x0, x1 in joined
                )
            ]
        )
    cells = {
        (col, k): _Cell(right=xs[col + 1])
        for col, ys in enumerate(columns)
        for k in range(max(len(ys) - 1, 0))
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
        if box[2] - box[0] < 0.5 or not text.strip():
            # Spaces carry no position of their own: a generated space has no box and a real one
            # can end past a column rule (manual page 21). They stay with the previous character.
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
            outside.append((text, box[0], cy))
            continue
        last_cell = cells[(col, index)]
        last_cell.chars.append((text, box))
        if mcid is not None:
            mcid_columns.setdefault(mcid, set()).add(col)
    mcid_box_columns: dict[int, set[int]] = {}
    for item in page.get("marked_content", ()):
        # Marked content without visible characters (an empty own cell) still has a position.
        cx = (item["x0"] + item["x1"]) / 2
        col = next((i for i in range(len(xs) - 1) if xs[i] <= cx < xs[i + 1]), None)
        if col is not None:
            mcid_box_columns.setdefault(item["mcid"], set()).add(col)

    # Lines above the table are grouped by height; within a line the PDF stream order is kept,
    # because a period's box can start right of the next character (1150826 「2.2.」).
    above = [(index, item) for index, item in enumerate(outside) if item[2] < table_top]
    lines: list[list[Any]] = []
    for index, (text, _, cy) in sorted(above, key=lambda pair: pair[1][2]):
        if lines and cy - lines[-1][0] <= 5:
            lines[-1][1].append((index, text))
        else:
            lines.append([cy, [(index, text)]])
    sections: dict[str, str] = {}
    for _, parts in lines:
        joined = "".join(text for _, text in sorted(parts))
        squeezed = "".join(joined.split())
        for item in _SPECS:
            match = item.section_re.fullmatch(squeezed)
            if match:
                sections[item.name] = f"{match.group(1)} {match.group(2)}"
    page_text = _squeeze("".join(char["text"] for char in chars))
    printed = _PRINTED_PAGE_RE.search(page_text)
    version = _VERSION_RE.search(page_text)
    approved = _APPROVED_DATE_RE.search(page_text)

    header_bottom = None
    names = None
    spec = None
    first_column = columns[0]
    for k in range(len(first_column) - 1):
        if _squeeze(cells[(0, k)].own_text()) in _ANCHORS:
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
            spec = next((item for item in _SPECS if names in item.variants), None)
            if spec is None:
                raise CdcManualLayoutError("LAYOUT_HEADER_MISMATCH", f"page {page['page_number']}")
            break
    return _PageTable(
        number=int(page["page_number"]),
        printed_page=int(printed.group(1)) if printed else None,
        version=version.group(1) if version else None,
        approved_date_raw=approved.group(1) if approved else None,
        sections=sections,
        spec=spec,
        xs=xs,
        columns=columns,
        cells=cells,
        has_text=bool(chars),
        header_bottom=header_bottom,
        names=names,
        table_rows=page.get("table_rows") or [],
        mcid_columns=mcid_columns,
        mcid_box_columns=mcid_box_columns,
        mcid_text={key: "".join(value) for key, value in mcid_text.items()},
    )


def _child_column(table: _PageTable, child: list[int]) -> int | None:
    columns = set().union(*(table.mcid_columns.get(mcid, set()) for mcid in child))
    if not columns:
        # Only a cell without visible characters falls back to its marked-content boxes.
        columns = set().union(*(table.mcid_box_columns.get(mcid, set()) for mcid in child))
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


def _parse_table(layout: dict[str, Any], spec: CdcTableSpec) -> CdcSpecimenLayoutResult:
    """Return one kind of table's rows in page order, or raise CdcManualLayoutError."""

    if not isinstance(layout, dict) or layout.get("layout_schema_version") != 1:
        raise CdcManualLayoutError("LAYOUT_SCHEMA_INVALID")
    try:
        pages = sorted(layout["pages"], key=lambda page: int(page["page_number"]))
        tables: list[_PageTable] = []
        for page in pages:
            table = _read_page(page)
            if table is not None and not table.has_text:
                raise CdcManualLayoutError("LAYOUT_NO_TEXT_LAYER", f"page {page['page_number']}")
            if not tables and (table is None or table.spec is not spec):
                continue
            if table is None or (table.names is not None and table.spec is not spec):
                # This kind of table ends at the first page without one, or with another header.
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
        section = table.sections.get(spec.name) or section
        if section is None:
            raise CdcManualLayoutError("LAYOUT_SECTION_MISSING", f"page {table.number}")
        table.resolved_section = section
        if table.version is None or table.approved_date_raw is None:
            raise CdcManualLayoutError("LAYOUT_VERSION_MISSING", f"page {table.number}")
        if (table.version, table.approved_date_raw) != (
            tables[0].version,
            tables[0].approved_date_raw,
        ):
            raise CdcManualLayoutError("LAYOUT_VERSION_CONFLICT", f"page {table.number}")
        width = len(table.columns)
        rows = [row for row in table.table_rows if any(child is not None for child in row)]
        header_rows = [
            index
            for index, row in enumerate(rows)
            if any(
                child is not None
                and _squeeze("".join(table.mcid_text.get(mcid, "") for mcid in child))
                == spec.anchor
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

        key_columns = [index for index, name in enumerate(table.names) if name in spec.key_fields]
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
        values = tuple(by_name.get(name) for name in spec.fields)
        display = {
            name: cell.group.display_text()  # type: ignore[union-attr]
            for name, cell in zip(table.names or (), covering)
        }
        display_values = tuple(display.get(name) for name in spec.fields)
        if not any(values):
            raise CdcManualLayoutError("LAYOUT_EMPTY_ROW", f"page {table.number}")
        result_rows.append(
            CdcSpecimenRow(
                values=values,
                locator={
                    "locator_type": "cdc_pdf_row",
                    "pdf_page": table.number,
                    "printed_page": table.printed_page,
                    "table_section": table.resolved_section,
                    "row_bbox": [
                        round(table.xs[0]),
                        round(top),
                        round(table.xs[-1]),
                        round(bottom),
                    ],
                },
                source_row_sha256=sha256_bytes(canonical_json_bytes(list(values))),
                display_values=display_values,
                field_names=spec.fields,
            )
        )
    return CdcSpecimenLayoutResult(
        rows=result_rows,
        summary={
            "rules_version": CDC_MANUAL_LAYOUT_RULES_VERSION,
            "table": spec.name,
            "manual_version": tables[0].version,
            "approved_date_raw": tables[0].approved_date_raw,
            "table_pages": [table.number for table in tables],
            "continuation_pages": continuation_pages,
            "page_joins": joins,
            "rows": len(result_rows),
            # One count per column order the manual prints for this table, in spec order.
            "variant_rows": [
                sum(1 for table, *_ in bands if table.names == variant) for variant in spec.variants
            ],
        },
    )


def parse_cdc_specimen_layout(layout: dict[str, Any]) -> CdcSpecimenLayoutResult:
    """Return chapter 2 specimen rows in page order, or raise CdcManualLayoutError."""

    return _parse_table(layout, CDC_SPECIMEN_SPEC)


def parse_cdc_testing_locations(layout: dict[str, Any]) -> CdcSpecimenLayoutResult:
    """Return chapter 7 testing-location rows in page order, or raise CdcManualLayoutError."""

    return _parse_table(layout, CDC_TESTING_LOCATION_SPEC)


def parse_cdc_receiving_units(layout: dict[str, Any]) -> CdcSpecimenLayoutResult:
    """Return the chapter 7 receiving-unit contacts, or raise CdcManualLayoutError."""

    return _parse_table(layout, CDC_RECEIVING_UNIT_SPEC)
