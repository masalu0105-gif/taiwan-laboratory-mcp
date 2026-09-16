"""CDC manual revision table (owner 2026-09-16, OD-18): which pages changed and why.

The revision table is a landscape document whose three outer columns are 修正規定, 現行規定 and
說明. The first two hold pictures of the manual's own tables, so only the change itself is read:
the printed page the entry points at, its subject line and the 說明 text. A change that runs onto
the next page keeps one entry. Fixtures are synthetic layouts with the shapes measured on the
1150826 revision table (29 landscape pages).
"""

import pytest

BLACK = [0, 0, 0]
OUTER_XS = (29.4, 398.1, 766.7, 823.4)


class _RevisionPage:
    """A landscape revision page: three outer columns and any number of row bands."""

    def __init__(self, number, *, top=90.0, xs=OUTER_XS):
        self.number = number
        self.xs = xs
        self.top = top
        self.bottom = top
        self.segments = []
        self.chars = []
        self._text("製表日期：115年08月26日", 600.0, 60.0)

    def _text(self, text, left, top, *, size=6.0, height=8.0):
        for index, char in enumerate(text):
            x0 = left + index * size
            self.chars.append(
                {"text": char, "x0": x0, "y0": top, "x1": x0 + size - 1, "y1": top + height}
            )

    def rule(self, y, x0, x1):
        self.segments.append({"x0": x0, "y0": y - 0.25, "x1": x1, "y1": y + 0.25, "color": BLACK})

    def band(self, height, cells, *, inner=()):
        """Add one outer row: `cells` is the text of the three outer columns."""

        top, bottom = self.bottom, self.bottom + height
        self.rule(top, self.xs[0], self.xs[-1])
        self.rule(bottom, self.xs[0], self.xs[-1])
        for column, text in enumerate(cells):
            if not text:
                continue
            for line, content in enumerate(text.split("\n")):
                self._text(content, self.xs[column] + 3, top + 4 + line * 12)
        # A nested table inside an outer cell: its column rules stay well inside the band.
        for x in inner:
            self.segments.append(
                {"x0": x - 0.25, "y0": top + 8, "x1": x + 0.25, "y1": bottom - 8, "color": BLACK}
            )
        self.bottom = bottom

    def build(self):
        segments = list(self.segments)
        for x in self.xs:
            segments.append(
                {"x0": x - 0.25, "y0": self.top, "x1": x + 0.25, "y1": self.bottom, "color": BLACK}
            )
        return {
            "page_number": self.number,
            "width": 842.0,
            "height": 595.0,
            "segments": segments,
            "chars": list(self.chars),
            "marked_content": [],
            "table_rows": [],
        }


def _layout(*pages):
    return {"layout_schema_version": 1, "pages": [page.build() for page in pages]}


def _header(page):
    page.band(24, ("修正規定", "現行規定", "說明"))


def _first_page():
    page = _RevisionPage(1)
    _header(page)
    page.band(
        200,
        ("(P6)傷寒、副傷寒\n肛門拭子", "(P6)傷寒、副傷寒\n糞便檢體", "修訂採檢\n項目、採\n檢目的"),
        inner=(100.0, 220.0, 470.0, 590.0),
    )
    return page


def _continuation_page():
    page = _RevisionPage(2)
    _header(page)
    # No 說明: this band carries the rest of the previous entry's tables.
    page.band(200, ("以無菌容器", "以無菌容器", ""), inner=(100.0, 470.0))
    return page


def _range_page():
    page = _RevisionPage(3)
    _header(page)
    page.band(
        120,
        ("(P74-79)4.傳染病檢體包裝及運送標準作業程序", "舊版包裝步驟", "修訂包裝\n步驟與示\n意圖"),
    )
    page.band(120, ("「疾管署」", "「本署」", "統一調整\n文字表達\n方式"))
    return page


def test_each_change_is_one_entry_with_its_page_subject_and_reason():
    from taiwan_lab_mcp.importers.cdc_manual_layout import parse_cdc_revision_entries

    result = parse_cdc_revision_entries(_layout(_first_page(), _continuation_page()))

    (row,) = result.rows
    assert row.fields() == {
        "page_reference_raw": "6",
        "subject_raw": "傷寒、副傷寒",
        "explanation_raw": "修訂採檢項目、採檢目的",
    }
    assert row.locator == {
        "locator_type": "cdc_pdf_row",
        "pdf_page": 1,
        "printed_page": None,
        "table_section": "修訂對照表",
        "row_bbox": [29, 114, 823, 314],
    }
    # The band on page 2 has no 說明, so it stays part of the same change.
    assert row.continues_on_pages == (2,)
    assert (result.summary["rows"], result.summary["compiled_date_raw"]) == (1, "115年08月26日")
    assert result.summary["table_pages"] == [1, 2]


def test_a_page_range_and_a_change_without_a_page_reference_are_both_kept():
    from taiwan_lab_mcp.importers.cdc_manual_layout import parse_cdc_revision_entries

    rows = parse_cdc_revision_entries(_layout(_range_page())).rows

    assert [row.fields()["page_reference_raw"] for row in rows] == ["74-79", None]
    assert [row.fields()["subject_raw"] for row in rows] == [
        "4.傳染病檢體包裝及運送標準作業程序",
        None,
    ]
    assert rows[1].fields()["explanation_raw"] == "統一調整文字表達方式"


def test_a_revision_page_that_is_not_three_columns_is_rejected():
    from taiwan_lab_mcp.importers.cdc_manual_layout import (
        CdcManualLayoutError,
        parse_cdc_revision_entries,
    )

    page = _RevisionPage(1, xs=(29.4, 398.1, 823.4))
    _header(page)
    page.band(80, ("(P6)傷寒", "舊", "修訂"))

    with pytest.raises(CdcManualLayoutError) as error:
        parse_cdc_revision_entries(_layout(page))
    assert error.value.code == "LAYOUT_REVISION_SHAPE"


def test_a_change_before_any_entry_is_rejected():
    from taiwan_lab_mcp.importers.cdc_manual_layout import (
        CdcManualLayoutError,
        parse_cdc_revision_entries,
    )

    page = _RevisionPage(1)
    _header(page)
    page.band(80, ("肛門拭子", "糞便檢體", ""))

    with pytest.raises(CdcManualLayoutError) as error:
        parse_cdc_revision_entries(_layout(page))
    assert error.value.code == "LAYOUT_REVISION_ORPHAN_ROW"
