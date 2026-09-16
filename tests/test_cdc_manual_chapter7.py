"""CDC manual chapter 7 (owner 2026-09-16, OD-18): where each test is sent and how long it takes.

Chapter 7 tables have the same shape as chapter 2 but their own columns: 傳染病名稱、採檢單位、
採檢項目、檢驗方法、檢驗期限、收件單位、實驗室生物安全等級(BSL)、備註. Section 7.7 (屍體解剖檢體)
prints 檢驗期間 instead of 檢驗期限 and has no BSL column; section 7.9 lists the receiving units'
phone, fax and address. Fixtures are synthetic layouts with the shapes measured on the 1150826
manual (pages 93-121).
"""

import importlib.util
from pathlib import Path

import pytest

PAGES = None


def _pages():
    global PAGES
    if PAGES is None:
        path = Path(__file__).with_name("test_cdc_manual_layout.py")
        spec = importlib.util.spec_from_file_location("cdc_manual_layout_pages", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        PAGES = module
    return PAGES


LOCATION_HEADER = (
    "傳染病\n名稱",
    "採檢單位",
    "採檢項目",
    "檢驗方法",
    "檢驗期限",
    "收件單位",
    "實驗室生物\n安全等級(BSL)",
    "備註",
)
AUTOPSY_HEADER = (
    "傳染病\n名稱",
    "採檢單位",
    "採檢項目",
    "檢驗方法",
    "檢驗期間",
    "收件單位",
    "備註",
)
UNIT_HEADER = ("單位名稱", "電話", "傳真", "地址")
UNIT_XS = (22.7, 160.0, 280.0, 400.0, 558.6)


def _location_page():
    pages = _pages()
    page = pages._Page(93, 83, heading="7.1.第一類法定傳染病", header=LOCATION_HEADER)
    disease = page.cell(0, 150, 250, "天花")
    unit = page.cell(1, 150, 250, "全國各醫療院所")
    limit = page.cell(4, 150, 250, "4-5 工作日")
    bsl = page.cell(6, 150, 250, "3")
    first = [
        page.cell(2, 150, 200, "水疱液、膿疱內容物"),
        page.cell(3, 150, 200, "病原體分離、鑑定"),
        # The 收件單位 column fits seven builder characters, so this unit name wraps.
        page.cell(5, 150, 200, "疾病管制署南港\n臨時辦公室"),
        page.cell(7, 150, 200, "1.新增送驗單及條碼。"),
    ]
    page.tr([disease], [unit], [first[0]], [first[1]], [limit], [first[2]], [bsl], [first[3]])
    second = [
        page.cell(2, 200, 250, "確認病毒株"),
        page.cell(3, 200, 250, "全基因體定序"),
        page.cell(5, 200, 250, "疾病管制署\n中區實驗室"),
        page.cell(7, 200, 250, "-"),
    ]
    page.tr(None, None, None, None, *([child] for child in second))
    return page


def _autopsy_page():
    pages = _pages()
    page = pages._Page(
        120, 110, heading="7.7.（疑似）傳染病屍體解剖檢體", xs=pages.SEVEN_XS, header=AUTOPSY_HEADER
    )
    cells = [
        page.cell(0, 150, 200, "疑似傳染病"),
        page.cell(1, 150, 200, "法務部法醫研究所"),
        page.cell(2, 150, 200, "抗凝固全血"),
        page.cell(3, 150, 200, "病原體檢測"),
        page.cell(4, 150, 200, "14 個工作日"),
        page.cell(5, 150, 200, "疾病管制署\n南港臨時辦公室"),
        page.cell(6, 150, 200, "-"),
    ]
    page.tr(*([cell] for cell in cells))
    return page


def _unit_page():
    pages = _pages()
    page = pages._Page(121, 111, heading="7.9.收件單位聯絡方式", xs=UNIT_XS, header=UNIT_HEADER)
    # 7.9 prints wide columns, so these values stay on one line each.
    first = [
        page.cell(0, 150, 200, "疾病管制署南港臨時辦公室"),
        page.cell(1, 150, 200, "02-81735678"),
        page.cell(2, 150, 200, "02-27850288"),
        page.cell(3, 150, 200, "11529 台北市南港區研究院路二段 128 號"),
    ]
    page.tr(*([cell] for cell in first))
    second = [
        page.cell(0, 200, 250, "疾病管制署中區實驗室"),
        page.cell(1, 200, 250, "04-24737980"),
        page.cell(2, 200, 250, "04-24737981"),
        page.cell(3, 200, 250, "40855 台中市南屯區黎明路二段 501 號"),
    ]
    page.tr(*([cell] for cell in second))
    return page


def _layout(*pages):
    return _pages()._layout(*pages)


def test_chapter_7_rows_keep_the_official_columns_and_merged_cells():
    from taiwan_lab_mcp.importers.cdc_manual_layout import parse_cdc_testing_locations

    result = parse_cdc_testing_locations(_layout(_location_page()))

    assert [row.fields() for row in result.rows] == [
        {
            "disease": "天花",
            "collecting_unit": "全國各醫療院所",
            "specimen": "水疱液、膿疱內容物",
            "method": "病原體分離、鑑定",
            "turnaround_raw": "4-5 工作日",
            "testing_period_raw": None,
            "receiving_unit": "疾病管制署南港\n臨時辦公室",
            "bsl_raw": "3",
            "notes": "1.新增送驗單及條碼。",
        },
        {
            "disease": "天花",
            "collecting_unit": "全國各醫療院所",
            "specimen": "確認病毒株",
            "method": "全基因體定序",
            "turnaround_raw": "4-5 工作日",
            "testing_period_raw": None,
            "receiving_unit": "疾病管制署\n中區實驗室",
            "bsl_raw": "3",
            "notes": "-",
        },
    ]
    first = result.rows[0]
    assert first.locator == {
        "locator_type": "cdc_pdf_row",
        "pdf_page": 93,
        "printed_page": 83,
        "table_section": "7.1 第一類法定傳染病",
        "row_bbox": [23, 150, 559, 200],
    }
    # Owner 2026-09-15 chose B: the display text joins lines the column width broke.
    assert first.display_fields()["receiving_unit"] == "疾病管制署南港臨時辦公室"
    assert first.fields()["receiving_unit"] == "疾病管制署南港\n臨時辦公室"
    assert (result.summary["rows"], result.summary["manual_version"]) == (2, "1150826")


def test_the_autopsy_section_uses_its_own_period_column_and_has_no_bsl():
    from taiwan_lab_mcp.importers.cdc_manual_layout import parse_cdc_testing_locations

    (row,) = parse_cdc_testing_locations(_layout(_autopsy_page())).rows

    fields = row.fields()
    assert (fields["testing_period_raw"], fields["turnaround_raw"], fields["bsl_raw"]) == (
        "14 個工作日",
        None,
        None,
    )
    assert fields["collecting_unit"] == "法務部法醫研究所"
    assert row.locator["table_section"] == "7.7 （疑似）傳染病屍體解剖檢體"


def test_receiving_unit_contacts_are_read_as_their_own_table():
    from taiwan_lab_mcp.importers.cdc_manual_layout import parse_cdc_receiving_units

    result = parse_cdc_receiving_units(_layout(_unit_page()))

    assert [row.fields() for row in result.rows] == [
        {
            "unit_name": "疾病管制署南港臨時辦公室",
            "phone": "02-81735678",
            "fax": "02-27850288",
            "address": "11529 台北市南港區研究院路二段 128 號",
        },
        {
            "unit_name": "疾病管制署中區實驗室",
            "phone": "04-24737980",
            "fax": "04-24737981",
            "address": "40855 台中市南屯區黎明路二段 501 號",
        },
    ]
    assert result.rows[0].locator["table_section"] == "7.9 收件單位聯絡方式"
    assert result.rows[1].display_fields()["unit_name"] == "疾病管制署中區實驗室"


def test_each_chapter_reads_only_its_own_tables():
    from taiwan_lab_mcp.importers.cdc_manual_layout import (
        parse_cdc_receiving_units,
        parse_cdc_specimen_layout,
        parse_cdc_testing_locations,
    )

    pages = _pages()
    layout = _layout(pages._plague_page(), _location_page(), _autopsy_page(), _unit_page())

    specimens = parse_cdc_specimen_layout(layout)
    locations = parse_cdc_testing_locations(layout)
    units = parse_cdc_receiving_units(layout)

    assert [row.fields()["specimen"] for row in specimens.rows] == ["淋巴液", "血清"]
    assert specimens.summary["table_pages"] == [14]
    assert [row.fields()["method"] for row in locations.rows] == [
        "病原體分離、鑑定",
        "全基因體定序",
        "病原體檢測",
    ]
    assert locations.summary["table_pages"] == [93, 120]
    assert [row.fields()["phone"] for row in units.rows] == ["02-81735678", "04-24737980"]


def test_a_header_that_matches_no_chapter_is_still_rejected():
    from taiwan_lab_mcp.importers.cdc_manual_layout import (
        CdcManualLayoutError,
        parse_cdc_testing_locations,
    )

    pages = _pages()
    page = pages._Page(93, 83, heading="7.1.第一類", header=("傳染病名稱",) * 8)

    with pytest.raises(CdcManualLayoutError) as error:
        parse_cdc_testing_locations(_layout(page))
    assert error.value.code == "LAYOUT_HEADER_MISMATCH"
