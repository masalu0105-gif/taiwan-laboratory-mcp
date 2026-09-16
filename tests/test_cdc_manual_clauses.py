"""CDC manual chapters 3-6 (owner 2026-09-16): the numbered steps, not tables.

Chapter 3 is how each kind of specimen is collected, chapter 4 packing and transport, chapter 5
cleaning up a spill and chapter 6 cleaning the transport box. They print as numbered clauses
(3.5.2, 4.2.5) with figure captions in between, so they are read as blocks of text rather than
rows of a table. Fixtures are synthetic pages with the shapes measured on the 1150826 manual
(pages 69-92).
"""

import pytest


class _ProsePage:
    """A page of numbered clauses: lines placed top down, each with its own indent."""

    def __init__(self, number, printed):
        self.number = number
        self.chars = []
        self.y = 120.0
        self._line(f"頁碼：第{printed}頁/共 119 頁", 380.0, 76.5)
        self._line("版次：1150826 核准日期：115 年 08 月 26 日", 69.0, 92.9)

    def _line(self, text, left, top, size=7.0):
        for index, char in enumerate(text):
            x0 = left + index * size
            self.chars.append(
                {"text": char, "x0": x0, "y0": top, "x1": x0 + size - 1, "y1": top + 10}
            )

    def line(self, text, left=100.6):
        self._line(text, left, self.y)
        self.y += 15.0

    def build(self):
        return {
            "page_number": self.number,
            "width": 595.32,
            "height": 842.04,
            "segments": [],
            "chars": list(self.chars),
            "marked_content": [],
            "table_rows": [],
        }


def _layout(*pages):
    return {"layout_schema_version": 1, "pages": [page.build() for page in pages]}


def _first_page():
    page = _ProsePage(69, 59)
    page.line("3. 傳染病檢體採檢步驟", left=73.2)
    page.line("3.1.全血（whole blood）", left=84.5)
    page.line("3.1.1.適用傳染病項目：傷寒、副傷寒、侵襲性 b 型嗜血桿菌感", left=100.6)
    page.line("染症、李斯特菌症。", left=126.3)
    page.line("3.1.1.1.作業程序：以無菌針頭接上 10 mL 之注射筒做靜脈穿刺，抽取 10-", left=109.1)
    page.line("15 mL 血液，如為嬰兒或小孩，則只抽取 1-2 mL 血液。", left=140.2)
    page.line("圖 3.1（A）採血管。", left=67.9)
    page.line("（A-1）內容物為試管一根。", left=80.1)
    return page


def _second_page():
    page = _ProsePage(70, 60)
    page.line("續前條：檢體採檢後應立即送驗。", left=126.3)
    page.line("3.2 抗凝固全血（anti-coagulated whole blood）", left=70.2)
    page.line("3.2.1.適用疾病：瘧疾。使用含 EDTA 抗凝劑之紫頭管(圖", left=100.6)
    page.line("3.3B)，炭疽病使用含肝素抗凝劑之綠頭管。", left=133.0)
    return page


def test_each_numbered_clause_is_one_row_with_its_page():
    from taiwan_lab_mcp.importers.cdc_manual_layout import parse_cdc_manual_clauses

    result = parse_cdc_manual_clauses(_layout(_first_page()))

    assert [(row.fields()["clause_number"], row.fields()["block_kind"]) for row in result.rows] == [
        ("3", "clause"),
        ("3.1", "clause"),
        ("3.1.1", "clause"),
        ("3.1.1.1", "clause"),
        ("3.1", "figure"),
    ]
    # Lines the page width broke are joined; a space only where letters or digits meet.
    assert result.rows[2].fields()["text"] == (
        "3.1.1.適用傳染病項目：傷寒、副傷寒、侵襲性 b 型嗜血桿菌感染症、李斯特菌症。"
    )
    assert result.rows[3].fields()["text"] == (
        "3.1.1.1.作業程序：以無菌針頭接上 10 mL 之注射筒做靜脈穿刺，抽取 10-15 mL 血液，"
        "如為嬰兒或小孩，則只抽取 1-2 mL 血液。"
    )
    # A figure caption keeps its own number and the labels printed under it.
    figure = result.rows[4].fields()
    assert figure["text"] == "圖 3.1（A）採血管。（A-1）內容物為試管一根。"
    assert result.rows[0].fields()["chapter"] == "3"
    assert result.rows[0].locator == {
        "locator_type": "cdc_pdf_row",
        "pdf_page": 69,
        "printed_page": 59,
        "table_section": "3 傳染病檢體採檢步驟",
        "row_bbox": [73, 120, 156, 130],
    }
    assert (result.summary["rows"], result.summary["manual_version"]) == (5, "1150826")


def test_a_clause_that_runs_onto_the_next_page_stays_one_row():
    from taiwan_lab_mcp.importers.cdc_manual_layout import parse_cdc_manual_clauses

    rows = parse_cdc_manual_clauses(_layout(_first_page(), _second_page())).rows

    figure = next(row for row in rows if row.fields()["block_kind"] == "figure")
    assert figure.fields()["text"].endswith("續前條：檢體採檢後應立即送驗。")
    assert figure.continues_on_pages == (70,)
    # 「3.2 抗凝固全血」 prints a space instead of a dot and is still a clause.
    assert [row.fields()["clause_number"] for row in rows][-2:] == ["3.2", "3.2.1"]
    # 「3.3B)，炭疽病…」 is a reference to figure 3.3, not the start of clause 3.3.
    assert rows[-1].fields()["text"].endswith("(圖3.3B)，炭疽病使用含肝素抗凝劑之綠頭管。")


def test_clause_numbers_that_go_backwards_are_rejected():
    from taiwan_lab_mcp.importers.cdc_manual_layout import (
        CdcManualLayoutError,
        parse_cdc_manual_clauses,
    )

    page = _ProsePage(69, 59)
    page.line("3. 傳染病檢體採檢步驟", left=73.2)
    page.line("3.5.糞便檢體", left=84.5)
    page.line("3.4.尿液", left=84.5)

    with pytest.raises(CdcManualLayoutError) as error:
        parse_cdc_manual_clauses(_layout(page))
    assert error.value.code == "LAYOUT_CLAUSE_ORDER"


def test_chapter_2_captions_on_the_same_page_are_not_read_as_chapter_3():
    # Chapter 3 starts halfway down page 69; above it the page still carries chapter 2 figures.
    from taiwan_lab_mcp.importers.cdc_manual_layout import parse_cdc_manual_clauses

    page = _ProsePage(69, 59)
    page.line("圖 2.5（A）細菌專用採檢拭子。", left=67.9)
    page.line("（A-1）內容物為棉棒一根。", left=80.1)
    page.line("3. 傳染病檢體採檢步驟", left=73.2)
    page.line("3.1.全血（whole blood）", left=84.5)

    rows = parse_cdc_manual_clauses(_layout(page)).rows

    assert [row.fields()["clause_number"] for row in rows] == ["3", "3.1"]
    assert all("圖 2.5" not in (row.fields()["text"] or "") for row in rows)
