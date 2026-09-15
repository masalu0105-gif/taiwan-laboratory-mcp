"""CDC manual chapter 2 tables rebuilt from a normalized page layout (ADR 0003).

Owner 2026-09-15: 「A 加翻頁，手冊繼續做第三步」. The fixtures are synthetic layouts with the
shapes measured on the 1150826 manual: black ruling lines, per-character boxes in stream order
and Word table tags where continuation cells come before a row's own cells.
"""

import pytest

from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes

EIGHT_XS = (22.7, 77.1, 130.3, 184.6, 239.3, 338.8, 394.8, 463.4, 558.6)
SEVEN_XS = (42.6, 111.6, 164.1, 217.4, 297.9, 390.1, 442.9, 567.0)
EIGHT_HEADER = (
    "傳染病\n名稱",
    "採檢項目",
    "採檢目的",
    "採檢時間",
    "採檢量及規定",
    "送驗方式",
    "應保存種類\n(應保存時間)",
    "注意事項",
)
SEVEN_HEADER = tuple(name for name in EIGHT_HEADER if not name.startswith("應保存"))
FIELDS = (
    "disease",
    "specimen",
    "purpose",
    "collection_time",
    "volume_requirement",
    "transport_method",
    "retention_raw",
    "notes",
)
BLACK = [0, 0, 0]
RED = [255, 0, 0]


MANUAL_VERSION = ("1150826", "115年08月26日")


class _Page:
    def __init__(
        self,
        number,
        printed,
        *,
        heading=None,
        xs=EIGHT_XS,
        header=EIGHT_HEADER,
        version=MANUAL_VERSION,
    ):
        self.number = number
        self.xs = xs
        self.segments = []
        self.chars = []
        self.table_rows = []
        self.marked_content = []
        self.mcid = 0
        self.top = 120.0
        self.bottom = 120.0
        self._text(f"頁碼：第{printed}頁/共 119 頁", 380.0, 60.0, None)
        if version:
            # Every manual page header prints the edition and its approval date.
            self._text(f"版次：{version[0]} 核准日期：{version[1]}", 300.0, 75.0, None)
        if heading:
            self._text(heading, 60.0, 105.0, None)
        if header:
            self.tr(*[[self.cell(col, 120, 150, name)] for col, name in enumerate(header)])

    def _text(self, text, left, top, mcid):
        for line_index, line in enumerate(text.split("\n")):
            for char_index, char in enumerate(line):
                x0 = left + char_index * 6
                y0 = top + line_index * 12
                self.chars.append(
                    {"text": char, "x0": x0, "y0": y0, "x1": x0 + 5, "y1": y0 + 10, "mcid": mcid}
                )

    def rule(self, col, y, *, color=BLACK, gap=0.0):
        left, right = self.xs[col], self.xs[col + 1]
        self.segments.append(
            {"x0": left + gap, "y0": y - 0.25, "x1": right - gap, "y1": y + 0.25, "color": color}
        )

    def cell(self, col, top, bottom, text):
        self.rule(col, top)
        self.rule(col, bottom)
        self.bottom = max(self.bottom, bottom)
        self.mcid += 1
        if text:
            self._text(text, self.xs[col] + 3, top + 3, self.mcid)
        return self.mcid

    def tr(self, *children):
        self.table_rows.append([None if child is None else list(child) for child in children])

    def build(self):
        segments = list(self.segments)
        for x in self.xs:
            segments.append(
                {"x0": x - 0.25, "y0": self.top, "x1": x + 0.25, "y1": self.bottom, "color": BLACK}
            )
        return {
            "page_number": self.number,
            "width": 595.32,
            "height": 842.04,
            "segments": segments,
            "chars": list(self.chars),
            "marked_content": list(self.marked_content),
            "table_rows": [list(row) for row in self.table_rows],
        }


def _layout(*pages):
    return {"layout_schema_version": 1, "pages": [page.build() for page in pages]}


def _plague_page():
    page = _Page(14, 4, heading="2.1.第一類法定傳染病檢體")
    disease = page.cell(0, 150, 250, "鼠疫")
    lymph = page.cell(1, 150, 200, "淋巴液")
    serum = page.cell(1, 200, 250, "血清")
    purpose = page.cell(2, 150, 250, "病原體檢測")
    acute = page.cell(3, 150, 200, "急性期")
    recovery = page.cell(3, 200, 250, "恢復期")
    volume_1 = page.cell(4, 150, 200, "以無菌針筒\n吸取 1-2 mL")
    volume_2 = page.cell(4, 200, 250, "3 mL 血清")
    transport = page.cell(5, 150, 250, "2-8oC\n(B 類感染\n性物質\nP650 包裝)")
    retention_1 = page.cell(6, 150, 200, "菌株(30日)")
    retention_2 = page.cell(6, 200, 250, "血清(30日)")
    notes = page.cell(7, 150, 250, "1.高度危險")
    page.tr(
        [disease],
        [lymph],
        [purpose],
        [acute],
        [volume_1],
        [transport],
        [retention_1],
        [notes],
    )
    # Word lists the four cells merged from the row above first, then this row's own cells.
    page.tr(None, None, None, None, [serum], [recovery], [volume_2], [retention_2])
    return page


def _parse(layout):
    from taiwan_lab_mcp.importers.cdc_manual_layout import parse_cdc_specimen_layout

    return parse_cdc_specimen_layout(layout)


def _error(layout):
    from taiwan_lab_mcp.importers.cdc_manual_layout import CdcManualLayoutError

    with pytest.raises(CdcManualLayoutError) as error:
        _parse(layout)
    return error.value.code


def test_merged_cells_repeat_their_original_text_in_every_specimen_row():
    result = _parse(_layout(_plague_page()))

    assert [row.fields() for row in result.rows] == [
        {
            "disease": "鼠疫",
            "specimen": "淋巴液",
            "purpose": "病原體檢測",
            "collection_time": "急性期",
            "volume_requirement": "以無菌針筒\n吸取 1-2 mL",
            "transport_method": "2-8oC\n(B 類感染\n性物質\nP650 包裝)",
            "retention_raw": "菌株(30日)",
            "notes": "1.高度危險",
        },
        {
            "disease": "鼠疫",
            "specimen": "血清",
            "purpose": "病原體檢測",
            "collection_time": "恢復期",
            "volume_requirement": "3 mL 血清",
            "transport_method": "2-8oC\n(B 類感染\n性物質\nP650 包裝)",
            "retention_raw": "血清(30日)",
            "notes": "1.高度危險",
        },
    ]
    first = result.rows[0]
    assert first.locator == {
        "locator_type": "cdc_pdf_row",
        "pdf_page": 14,
        "printed_page": 4,
        "table_section": "2.1 第一類法定傳染病檢體",
        "row_bbox": [23, 150, 559, 200],
    }
    assert first.source_row_sha256 == sha256_bytes(
        canonical_json_bytes([first.fields()[name] for name in FIELDS])
    )
    assert result.summary["rows"] == 2
    assert result.summary["table_pages"] == [14]
    assert result.summary["manual_version"] == "1150826"
    assert result.summary["approved_date_raw"] == "115年08月26日"


def test_characters_in_pdf_stream_order_across_columns_stay_in_their_own_cells():
    layout = _layout(_plague_page())
    # A PDF may write a whole visual line across columns before the next line.
    layout["pages"][0]["chars"].sort(key=lambda char: (char["y0"], char["x0"]))

    rows = _parse(layout).rows

    assert rows[0].fields()["volume_requirement"] == "以無菌針筒\n吸取 1-2 mL"
    assert rows[0].fields()["transport_method"] == "2-8oC\n(B 類感染\n性物質\nP650 包裝)"


def test_space_that_crosses_a_column_rule_stays_with_the_previous_character():
    # Manual page 21: the space after 「3」 in 「3 mL 血清」 ends past the column rule.
    layout = _layout(_plague_page())
    chars = layout["pages"][0]["chars"]
    three = next(index for index, char in enumerate(chars) if char["text"] == "3")
    space = chars[three + 1]
    assert space["text"] == " "
    space.update(x0=EIGHT_XS[5] - 1.5, x1=EIGHT_XS[5] + 2.0)

    rows = _parse(layout).rows

    assert rows[1].fields()["volume_requirement"] == "3 mL 血清"
    assert rows[1].fields()["transport_method"] == "2-8oC\n(B 類感染\n性物質\nP650 包裝)"


def test_marked_content_without_characters_does_not_move_a_cell_with_text():
    # Manual page 55: a cell's tag also lists invisible marked content whose box sits in the
    # next column; the visible characters decide the column.
    page = _plague_page()
    page.marked_content.append(
        {"mcid": 999, "x0": EIGHT_XS[5] + 1, "y0": 160.0, "x1": EIGHT_XS[5] + 4, "y1": 170.0}
    )
    page.table_rows[1][4] = [*page.table_rows[1][4], 999]

    rows = _parse(_layout(page)).rows

    assert rows[0].fields()["volume_requirement"] == "以無菌針筒\n吸取 1-2 mL"


def test_red_underlines_and_lines_that_do_not_reach_the_column_rules_are_not_row_boundaries():
    page = _plague_page()
    page.rule(4, 175, color=RED, gap=1.4)
    page.rule(1, 175, gap=1.4)

    assert len(_parse(_layout(page)).rows) == 2


def test_page_header_box_lines_above_the_table_are_not_table_rules():
    page = _plague_page()
    # The 1150826 page header box (編號／版次／頁碼) has lines that end on table column rules.
    for y in (67.7, 84.5, 101.2):
        for col in (1, 2, 4, 6):
            page.rule(col, y)
    for x in (40.4, 198.2, 375.3, 539.3):
        page.segments.append(
            {"x0": x - 0.25, "y0": 67.7, "x1": x + 0.25, "y1": 84.5, "color": BLACK}
        )

    result = _parse(_layout(page))

    assert result.rows[0].locator["table_section"] == "2.1 第一類法定傳染病檢體"
    assert [row.fields()["specimen"] for row in result.rows] == ["淋巴液", "血清"]


def test_section_heading_reads_in_stream_order_even_when_a_period_box_sits_further_right():
    # Manual 1150826: the box of the period in 「2.2.」 starts right of 「第」, so sorting by x read
    # 「2.2 第.二類…」.
    layout = _layout(_plague_page())
    chars = layout["pages"][0]["chars"]
    heading = [char for char in chars if 100 < char["y0"] < 118]
    assert "".join(char["text"] for char in heading) == "2.1.第一類法定傳染病檢體"
    heading[3].update(x0=heading[4]["x0"] + 2, x1=heading[4]["x0"] + 4)

    rows = _parse(layout).rows

    assert rows[0].locator["table_section"] == "2.1 第一類法定傳染病檢體"


def test_seven_column_table_has_no_retention_column():
    page = _Page(51, 41, heading="2.6.非法定傳染病檢體", xs=SEVEN_XS, header=SEVEN_HEADER)
    cells = [
        page.cell(col, 150, 200, text)
        for col, text in enumerate(
            ("腹瀉群聚", "新鮮糞便", "病毒檢測", "立即採檢", "大於 3 g", "2-8oC", "1.衛生局")
        )
    ]
    page.tr(*[[mcid] for mcid in cells])

    (row,) = _parse(_layout(page)).rows

    assert row.fields()["retention_raw"] is None
    assert row.fields()["transport_method"] == "2-8oC"
    assert row.locator["table_section"] == "2.6 非法定傳染病檢體"


def _typhoid_pages(
    *,
    next_header=EIGHT_HEADER,
    next_xs=EIGHT_XS,
    retention_top="",
    transport=("2-8oC\n(B 類感染\n性物質\nP650 包", "裝)"),
    next_version=MANUAL_VERSION,
):
    first = _Page(16, 6, heading="2.2.第二類法定傳染病檢體")
    cells = [
        first.cell(col, 150, 200, text)
        for col, text in enumerate(
            (
                "傷寒",
                "肛門拭子",
                "病原體檢測",
                "未投藥前",
                "以無菌之細菌拭子",
                transport[0],
                "菌株(30日)",
                "見 2.8.6",
            )
        )
    ]
    first.tr(*[[mcid] for mcid in cells])
    second = _Page(17, 7, xs=next_xs, header=next_header, version=next_version)
    for col in (0, 2, 3):
        second.cell(col, 150, 200, "")
    retention = second.cell(6, 150, 200, retention_top)
    urine = second.cell(1, 150, 200, "尿液")
    volume = second.cell(4, 150, 200, "10 mL 中段尿液")
    overflow = second.cell(5, 150, 200, transport[1])
    notes = second.cell(7, 150, 200, "尿液檢體")
    second.tr(None, None, None, None, [overflow], [urine], [volume], [notes])
    dengue = [
        second.cell(col, 200, 250, text)
        for col, text in enumerate(
            ("登革熱", "血清", "抗體檢測", "急性期", "3 mL", "2-8oC", "血清(30日)", "1.血清")
        )
    ]
    second.tr(*[[mcid] for mcid in dengue])
    assert retention
    return first, second


def test_text_that_overflows_onto_the_next_page_joins_the_merged_cell_above():
    rows = _parse(_layout(*_typhoid_pages())).rows

    assert [row.fields()["specimen"] for row in rows] == ["肛門拭子", "尿液", "血清"]
    joined = "2-8oC\n(B 類感染\n性物質\nP650 包\n裝)"
    assert rows[0].fields()["transport_method"] == joined
    assert rows[1].fields() == {
        "disease": "傷寒",
        "specimen": "尿液",
        "purpose": "病原體檢測",
        "collection_time": "未投藥前",
        "volume_requirement": "10 mL 中段尿液",
        "transport_method": joined,
        "retention_raw": "菌株(30日)",
        "notes": "尿液檢體",
    }
    assert rows[1].locator["pdf_page"] == 17
    assert rows[1].locator["printed_page"] == 7
    assert rows[1].locator["table_section"] == "2.2 第二類法定傳染病檢體"
    assert rows[2].fields()["disease"] == "登革熱"


def test_page_without_a_header_continues_when_every_column_width_matches():
    rows = _parse(_layout(*_typhoid_pages(next_header=None))).rows

    assert [row.fields()["specimen"] for row in rows] == ["肛門拭子", "尿液", "血清"]
    assert rows[1].fields()["disease"] == "傷寒"


def _display_page():
    # Builder characters advance 6 pt; a full line leaves less room than the next word needs.
    page = _Page(14, 4, heading="2.2.第二類法定傳染病檢體")
    texts = (
        "傷寒\n副傷寒",
        "肛門拭子",
        "病原體檢測；血清\n型別鑑定",
        "發病後(30\n日)內",
        "以無菌試管收集以無菌試管收集 3\nmL 血清",
        "送驗前請參考說明第\n3.4節。",
        "菌株(30日)",
        "尿液檢體(參考第3.4節)採自\n下列患者：\n1.確定合併感染埃及血吸蟲患者\n。\n2.無症狀帶菌者",
    )
    page.tr(*[[page.cell(col, 150, 250, text)] for col, text in enumerate(texts)])
    return page


def test_display_text_joins_lines_that_ran_out_of_room_and_keeps_author_line_breaks():
    # Owner 2026-09-15 chose B: cell text reads as one line except before 「1.」「2.」 items.
    (row,) = _parse(_layout(_display_page())).rows

    assert row.fields()["purpose"] == "病原體檢測；血清\n型別鑑定"
    assert row.display_fields() == {
        # 「傷寒」 stops with room to spare, so the author broke the line: both names stay apart.
        "disease": "傷寒\n副傷寒",
        "specimen": "肛門拭子",
        "purpose": "病原體檢測；血清型別鑑定",
        # 「日」 alone would fit, but 「)」 cannot start a line, so 「日)」 moved down together.
        "collection_time": "發病後(30日)內",
        "volume_requirement": "以無菌試管收集以無菌試管收集 3 mL 血清",
        # 「3.4節」 is a section number, not a list item.
        "transport_method": "送驗前請參考說明第3.4節。",
        "retention_raw": "菌株(30日)",
        # 「。」 cannot start a line either: its line is joined whatever room was left.
        "notes": "尿液檢體(參考第3.4節)採自下列患者：\n1.確定合併感染埃及血吸蟲患者。\n2.無症狀帶菌者",
    }


def test_display_text_joins_a_full_line_with_its_overflow_on_the_next_page():
    # Nine builder characters fill the transport column; the rest continues on the next page.
    rows = _parse(_layout(*_typhoid_pages(transport=("2-8oC(B類感", "染性物質)")))).rows

    assert rows[0].fields()["transport_method"] == "2-8oC(B類感\n染性物質)"
    assert rows[0].display_fields()["transport_method"] == "2-8oC(B類感染性物質)"
    assert rows[1].display_fields()["transport_method"] == "2-8oC(B類感染性物質)"
    assert rows[1].display_fields()["retention_raw"] == "菌株(30日)"


def _shifted(xs, amount):
    return tuple(x + (amount if index > 3 else 0) for index, x in enumerate(xs))


@pytest.mark.parametrize(
    ("build", "expected_code"),
    [
        (
            lambda: _layout(_Page(14, 4, heading="2.1.第一類", header=("傳染病名稱",) * 8)),
            "LAYOUT_HEADER_MISMATCH",
        ),
        (
            lambda: _layout(*_typhoid_pages(next_header=None, next_xs=_shifted(EIGHT_XS, 6))),
            "LAYOUT_HEADER_MISSING",
        ),
        (
            lambda: _layout(*_typhoid_pages(retention_top="菌株")),
            "LAYOUT_CONTINUATION_AMBIGUOUS",
        ),
        (lambda: _layout(_Page(14, 4, header=EIGHT_HEADER)), "LAYOUT_SECTION_MISSING"),
        (lambda: {"layout_schema_version": 1, "pages": []}, "LAYOUT_NO_TABLE"),
        # SDD 10.3: missing or contradicting edition information blocks the whole manual.
        (
            lambda: _layout(_Page(14, 4, heading="2.1.第一類", version=None)),
            "LAYOUT_VERSION_MISSING",
        ),
        (
            lambda: _layout(*_typhoid_pages(next_version=("1150827", "115年08月26日"))),
            "LAYOUT_VERSION_CONFLICT",
        ),
        (
            lambda: _layout(*_typhoid_pages(next_version=("1150826", "115年08月27日"))),
            "LAYOUT_VERSION_CONFLICT",
        ),
    ],
)
def test_layouts_that_cannot_be_read_safely_are_rejected(build, expected_code):
    assert _error(build()) == expected_code


def test_row_tags_with_a_different_cell_count_are_rejected():
    page = _plague_page()
    page.table_rows[2] = page.table_rows[2][1:]

    assert _error(_layout(page)) == "LAYOUT_TAG_WIDTH_MISMATCH"


def test_overflow_in_the_middle_of_a_page_is_rejected():
    page = _plague_page()
    serum, recovery, volume, retention = (child[0] for child in page.table_rows[2][4:])
    page.table_rows[2] = [None, None, None, None, [retention], [serum], [recovery], [volume]]

    assert _error(_layout(page)) == "LAYOUT_MID_PAGE_OVERFLOW"


def test_table_page_without_a_text_layer_is_rejected():
    layout = _layout(_plague_page())
    layout["pages"][0]["chars"] = []

    assert _error(layout) == "LAYOUT_NO_TEXT_LAYER"
