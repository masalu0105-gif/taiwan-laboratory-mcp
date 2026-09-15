"""CDC recognized laboratory roster (ODS): archive safety, merge semantics, 12 raw fields.

Owner 2026-09-15 asked to start the CDC source (「A 開始做疾管署」); SDD 10.4 puts the ODS
roster first. Every fixture here is synthetic and shaped like the official 1150914 roster.
"""

import io
import json
import zipfile
from xml.sax.saxutils import escape

import pytest

HEADER = (
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
MIMETYPE = b"application/vnd.oasis.opendocument.spreadsheet"
NAMESPACES = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
)


def cell(text="", *, rows=None, repeat=None, markup=None):
    attributes = ""
    if rows:
        attributes += f' table:number-rows-spanned="{rows}"'
    if repeat:
        attributes += f' table:number-columns-repeated="{repeat}"'
    body = markup if markup is not None else (f"<text:p>{escape(text)}</text:p>" if text else "")
    return f"<table:table-cell{attributes}>{body}</table:table-cell>"


def covered(repeat=None):
    attributes = f' table:number-columns-repeated="{repeat}"' if repeat else ""
    return f"<table:covered-table-cell{attributes}/>"


def row(*cells, repeat=None):
    attributes = f' table:number-rows-repeated="{repeat}"' if repeat else ""
    return f"<table:table-row{attributes}>{''.join(cells)}</table:table-row>"


TITLE_ROW = row(
    '<table:table-cell table:number-columns-spanned="12"><text:p>傳染病檢驗機構認可項目名冊</text:p>'
    "</table:table-cell>",
    covered(11),
    cell(repeat=16372),
)
HEADER_ROW = row(*(cell(name) for name in HEADER), cell(repeat=16372))
TRAILING_ROWS = row(cell(repeat=16384), repeat=1044990)

# Institution 097036: one certificate, two diseases, three method rows (merged like the roster).
KAOHSIUNG = [
    row(
        cell("097036", rows=3),
        cell("高雄市", rows=3),
        cell("合成總醫院附設診療服務處(050)", rows=3),
        cell("檢驗科", rows=3),
        cell("002", rows=2),
        cell("傷寒", rows=2),
        cell("確認", rows=2),
        cell("病原體分離、鑑定(A1)"),
        cell("高雄市合成區測試路5號", rows=3),
        cell("(07)000-1013", rows=3),
        cell("2028/12/31", rows=3),
        cell("2026/09/08", rows=3),
    ),
    row(covered(7), cell("血清型別鑑定(B2)"), covered(4)),
    row(
        covered(4),
        cell("002a"),
        cell("副傷寒"),
        cell("確認"),
        cell("病原體分離、鑑定(A1)"),
        covered(4),
    ),
]
# Institution 098029: proficiency testing not required; the same row appears twice upstream.
TAIPEI = [
    row(
        cell("098029", rows=2),
        cell("臺北市", rows=2),
        cell("合成檢驗所", rows=2),
        cell("醫檢部", rows=2),
        cell("090", rows=2),
        cell("梅毒", rows=2),
        cell("篩檢", rows=2),
        cell("抗體檢測-非特異性梅毒螺旋體試驗(RPR)(B16)"),
        cell("臺北市合成區測試街1號", rows=2),
        cell("(02)0000-0000#12", rows=2),
        cell("2027/06/30", rows=2),
        cell("無需能力試驗", rows=2),
    ),
    row(covered(7), cell("抗體檢測-非特異性梅毒螺旋體試驗(RPR)(B16)"), covered(4)),
]
# Institution 19SC0001: a real blank review cell below a dated one stays blank.
TAINAN = [
    row(
        cell("19SC0001"),
        cell("臺南市"),
        cell("合成醫院"),
        cell("檢驗醫學部"),
        cell("19SC"),
        cell("合成疾病"),
        cell("確認"),
        cell("核酸檢測(C1)"),
        cell("臺南市合成區1號"),
        cell("(06)000-0000"),
        cell("2029/01/01"),
        cell(""),
    ),
]
DATA_ROWS = KAOHSIUNG + TAIPEI + TAINAN


def content_xml(sheets, *, prefix=""):
    tables = "".join(
        f'<table:table table:name="{name}">{"".join(rows)}</table:table>' for name, rows in sheets
    )
    return (f'{prefix}<?xml version="1.0" encoding="UTF-8"?>' if not prefix else prefix) + (
        f"<office:document-content {NAMESPACES}><office:body><office:spreadsheet>"
        f"{tables}</office:spreadsheet></office:body></office:document-content>"
    )


def roster_rows(data_rows=DATA_ROWS):
    return [TITLE_ROW, HEADER_ROW, *data_rows, TRAILING_ROWS]


def ods_bytes(sheets=None, *, mimetype=MIMETYPE, content=None, extra_entries=()):
    sheets = (
        sheets
        if sheets is not None
        else [
            ("1150914名冊", roster_rows()),
            ("Sheet2", [row(cell(repeat=16384), repeat=1048576)]),
        ]
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if mimetype is not None:
            archive.writestr(zipfile.ZipInfo("mimetype"), mimetype)
        payload = content if content is not None else content_xml(sheets)
        info = zipfile.ZipInfo("content.xml")
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, payload.encode("utf-8") if isinstance(payload, str) else payload)
        for name, data in extra_entries:
            archive.writestr(name, data)
    return buffer.getvalue()


def _parse(payload, **kwargs):
    from taiwan_lab_mcp.importers.cdc_ods import parse_cdc_labs_ods

    return parse_cdc_labs_ods(payload, **kwargs)


def _error(payload, **kwargs):
    from taiwan_lab_mcp.importers.cdc_ods import CdcOdsImportError

    with pytest.raises(CdcOdsImportError) as error:
        _parse(payload, **kwargs)
    return error.value


def test_lab_01_certificate_disease_purpose_method_rows_remain_distinct():
    parsed = _parse(ods_bytes())

    assert len(parsed.rows) == 6
    kaohsiung = [
        item.fields() for item in parsed.rows if item.fields()["certificate_no"] == "097036"
    ]
    assert [(r["disease_code"], r["purpose"], r["method"]) for r in kaohsiung] == [
        ("002", "確認", "病原體分離、鑑定(A1)"),
        ("002", "確認", "血清型別鑑定(B2)"),
        ("002a", "確認", "病原體分離、鑑定(A1)"),
    ]
    # The roster repeats one row; both stay, told apart by their spreadsheet row numbers.
    taipei = [item for item in parsed.rows if item.fields()["certificate_no"] == "098029"]
    assert [item.expanded_row_number for item in taipei] == [6, 7]
    assert taipei[0].values == taipei[1].values
    assert parsed.summary["rows"] == 6
    assert parsed.summary["distinct_certificates"] == 3
    assert parsed.summary["distinct_diseases"] == 4
    assert parsed.summary["duplicate_logical_keys"] == 1


def test_lab_02_raw_twelve_fields_and_row_locator_are_returned():
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.cdc_ods import CDC_LABS_FIELD_NAMES

    parsed = _parse(ods_bytes())
    first = parsed.rows[0]

    assert parsed.sheet_name == "1150914名冊"
    assert first.expanded_row_number == 3  # title row 1, header row 2
    assert first.source_row_sha256 == sha256_bytes(canonical_json_bytes(list(first.values)))
    assert list(first.fields()) == list(CDC_LABS_FIELD_NAMES)
    assert first.fields() == {
        "certificate_no": "097036",
        "city": "高雄市",
        "institution": "合成總醫院附設診療服務處(050)",
        "department": "檢驗科",
        "disease_code": "002",
        "disease_name": "傷寒",
        "purpose": "確認",
        "method": "病原體分離、鑑定(A1)",
        "address": "高雄市合成區測試路5號",
        "phone": "(07)000-1013",
        "end_time": "2028/12/31",
        "latest_annual_pt_review_raw": "2026/09/08",
    }
    assert parsed.rows[2].fields()["disease_code"] == "002a"
    assert parsed.rows[5].fields()["certificate_no"] == "19SC0001"
    assert parsed.summary["sheet_name"] == "1150914名冊"
    assert parsed.summary["title_raw"] == "傳染病檢驗機構認可項目名冊"


def test_lab_03_only_declared_merge_spans_inherit_anchor_values():
    parsed = _parse(ods_bytes())
    third = parsed.rows[2].fields()
    # Covered cells take the value of the anchor whose span covers them.
    assert (third["certificate_no"], third["address"], third["end_time"]) == (
        "097036",
        "高雄市合成區測試路5號",
        "2028/12/31",
    )
    # A real blank cell is not forward-filled from the row above.
    assert parsed.rows[5].fields()["latest_annual_pt_review_raw"] == ""

    orphan = [row(*(covered() for _ in range(12)))]
    assert _error(ods_bytes([("1150914名冊", roster_rows(orphan))])).code == (
        "ODS_COVERED_CELL_WITHOUT_ANCHOR"
    )
    conflict = [KAOHSIUNG[0], TAINAN[0]]
    assert _error(ods_bytes([("1150914名冊", roster_rows(conflict))])).code == (
        "ODS_MERGE_SPAN_CONFLICT"
    )


def test_lab_04_pt_review_date_text_and_blank_round_trip():
    parsed = _parse(ods_bytes())
    values = [item.fields()["latest_annual_pt_review_raw"] for item in parsed.rows]
    assert values == ["2026/09/08"] * 3 + ["無需能力試驗"] * 2 + [""]
    assert parsed.summary["pt_review_kinds"] == {
        "date": 3,
        "not_required": 2,
        "blank": 1,
        "other": 0,
    }


def test_text_elements_keep_spaces_tabs_line_breaks_and_paragraphs():
    markup = (
        '<text:p>A<text:s text:c="2"/>B<text:tab/>C<text:line-break/>D</text:p>'
        "<text:p>第二段</text:p>"
    )
    special = [
        row(
            *(cell(value) for value in TAINAN_VALUES[:7]),
            cell(markup=markup),
            *(cell(value) for value in TAINAN_VALUES[8:]),
        )
    ]
    parsed = _parse(ods_bytes([("1150914名冊", roster_rows(special))]))
    assert parsed.rows[0].fields()["method"] == "A  B\tC\nD\n第二段"


TAINAN_VALUES = (
    "19SC0001",
    "臺南市",
    "合成醫院",
    "檢驗醫學部",
    "19SC",
    "合成疾病",
    "確認",
    "核酸檢測(C1)",
    "臺南市合成區1號",
    "(06)000-0000",
    "2029/01/01",
    "",
)


def _single(**overrides):
    values = dict(zip(HEADER, TAINAN_VALUES))
    values.update(overrides)
    return [row(*(cell(values[name]) for name in HEADER))]


@pytest.mark.parametrize(
    ("payload_factory", "expected_code"),
    [
        (lambda: b"<html>not a zip</html>", "ODS_NOT_ZIP"),
        (lambda: ods_bytes(mimetype=b"application/zip"), "ODS_MIMETYPE_MISMATCH"),
        (lambda: ods_bytes(mimetype=None), "ODS_MIMETYPE_MISMATCH"),
        (
            lambda: ods_bytes(content='<!DOCTYPE x [<!ENTITY a "b">]><x/>'),
            "ODS_XML_FORBIDDEN_DECLARATION",
        ),
        (
            lambda: ods_bytes(extra_entries=[("../evil.xml", b"x")]),
            "ODS_ARCHIVE_PATH_INVALID",
        ),
        (
            lambda: ods_bytes(
                [("1150914名冊", [TITLE_ROW, row(*(cell(n) for n in HEADER[:11]), cell("效期"))])]
            ),
            "ODS_HEADER_MISMATCH",
        ),
        (
            lambda: ods_bytes([("Sheet1", [row(cell(repeat=16384), repeat=100)])]),
            "ODS_SHEET_MISSING",
        ),
        (
            lambda: ods_bytes([("1150914名冊", roster_rows()), ("1150915名冊", roster_rows())]),
            "ODS_SHEET_AMBIGUOUS",
        ),
        (
            lambda: ods_bytes(
                [
                    (
                        "1150914名冊",
                        roster_rows(
                            [row(*(cell(value) for value in TAINAN_VALUES), cell("第13欄"))]
                        ),
                    )
                ]
            ),
            "ODS_EXTRA_COLUMN_VALUE",
        ),
        (
            lambda: ods_bytes([("1150914名冊", roster_rows(_single(結束時間="2029-01-01")))]),
            "ODS_END_DATE_INVALID",
        ),
        (
            lambda: ods_bytes([("1150914名冊", roster_rows(_single(結束時間="2029/02/30")))]),
            "ODS_END_DATE_INVALID",
        ),
        (
            lambda: ods_bytes([("1150914名冊", roster_rows(_single(檢驗方法="")))]),
            "ODS_REQUIRED_VALUE_MISSING",
        ),
        (lambda: ods_bytes([("1150914名冊", roster_rows([]))]), "ODS_NO_DATA_ROWS"),
    ],
)
def test_sdd_ods_01_contract_bundle(payload_factory, expected_code):
    assert _error(payload_factory()).code == expected_code


def test_trailing_blank_rows_repeated_a_million_times_are_skipped_without_expansion():
    # The official 1150914 roster ends with one blank row repeated 1,044,990 times.
    parsed = _parse(ods_bytes())
    assert parsed.summary["rows"] == 6


@pytest.mark.parametrize(
    ("limit", "at_limit", "one_over"),
    [
        ("max_rows", 6, 5),
        ("max_row_repeat", 2, 1),
        ("max_cell_text_bytes", len("抗體檢測-非特異性梅毒螺旋體試驗(RPR)(B16)".encode()), 50),
        ("max_depth", 7, 6),
    ],
)
def test_resource_limits_pass_at_the_limit_and_fail_one_over(limit, at_limit, one_over):
    from dataclasses import replace

    from taiwan_lab_mcp.importers.cdc_ods import DEFAULT_ODS_LIMITS

    rows = DATA_ROWS
    if limit == "max_row_repeat":
        rows = [*KAOHSIUNG, row(*(cell(value) for value in TAINAN_VALUES), repeat=2)]
    payload = ods_bytes([("1150914名冊", roster_rows(rows))])

    assert _parse(payload, limits=replace(DEFAULT_ODS_LIMITS, **{limit: at_limit})).rows
    error = _error(payload, limits=replace(DEFAULT_ODS_LIMITS, **{limit: one_over}))
    assert (error.code, limit in str(error)) == ("ODS_RESOURCE_LIMIT", True)


@pytest.mark.parametrize(
    "limit", ["max_archive_bytes", "max_content_bytes", "max_elements", "max_total_text_bytes"]
)
def test_byte_and_element_budgets_are_counted_from_the_actual_content(limit):
    from dataclasses import replace

    from taiwan_lab_mcp.importers.cdc_ods import DEFAULT_ODS_LIMITS

    payload = ods_bytes()
    parsed = _parse(payload)
    measured = {
        "max_archive_bytes": len(payload),
        "max_content_bytes": parsed.summary["content_xml_bytes"],
        "max_elements": parsed.summary["xml_elements"],
        "max_total_text_bytes": parsed.summary["cell_text_bytes"],
    }[limit]
    assert _parse(payload, limits=replace(DEFAULT_ODS_LIMITS, **{limit: measured})).rows
    error = _error(payload, limits=replace(DEFAULT_ODS_LIMITS, **{limit: measured - 1}))
    assert (error.code, limit in str(error)) == ("ODS_RESOURCE_LIMIT", True)


def test_default_limits_follow_sdd_10_4():
    from taiwan_lab_mcp.importers.cdc_ods import DEFAULT_ODS_LIMITS

    mib = 1024 * 1024
    assert DEFAULT_ODS_LIMITS.max_archive_bytes == 16 * mib
    assert DEFAULT_ODS_LIMITS.max_entries == 64
    assert DEFAULT_ODS_LIMITS.max_entry_bytes == 32 * mib
    assert DEFAULT_ODS_LIMITS.max_total_uncompressed_bytes == 64 * mib
    assert DEFAULT_ODS_LIMITS.max_compression_ratio == 100
    assert DEFAULT_ODS_LIMITS.max_content_bytes == 32 * mib
    assert DEFAULT_ODS_LIMITS.max_rows == 100_000
    assert DEFAULT_ODS_LIMITS.max_elements == 2_000_000
    assert DEFAULT_ODS_LIMITS.max_depth == 64
    assert DEFAULT_ODS_LIMITS.max_cell_text_bytes == 65_536
    assert DEFAULT_ODS_LIMITS.max_total_text_bytes == 32 * mib
    assert DEFAULT_ODS_LIMITS.max_row_repeat == 10_000
    assert DEFAULT_ODS_LIMITS.max_column_repeat == 16_384


def test_cli_validate_cdc_authorized_labs(tmp_path, capsys):
    from taiwan_lab_mcp.data_cli import main

    good = tmp_path / "roster.ods"
    good.write_bytes(ods_bytes())
    assert main(["validate", "cdc_authorized_labs", "--input", str(good), "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert (output["source_id"], output["validation_status"]) == ("cdc_authorized_labs", "passed")
    assert output["summary"]["rows"] == 6

    bad = tmp_path / "page.ods"
    bad.write_bytes(b"<html></html>")
    assert main(["validate", "cdc_authorized_labs", "--input", str(bad), "--json"]) == 4
    assert json.loads(capsys.readouterr().out) == {
        "source_id": "cdc_authorized_labs",
        "validation_status": "failed",
        "error_code": "ODS_NOT_ZIP",
    }
