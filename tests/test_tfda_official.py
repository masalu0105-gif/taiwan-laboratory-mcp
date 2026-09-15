"""TFDA official snapshot: curated build, labels, summary search and exact license lookup."""

import csv
import io
import sqlite3
import zipfile
from datetime import date, datetime, timezone

import pytest

from taiwan_lab_mcp.adapters.tfda import TFDAAdapter
from taiwan_lab_mcp.config import DataContext
from taiwan_lab_mcp.importers.tfda import TFDA_COLUMNS, build_tfda_snapshot
from taiwan_lab_mcp.tfda_store import evaluate_temporal

FIRST = "衛部醫器輸字第000001號"
TFDA_NOT_OFFICIAL_NOTE = "非食藥署官方服務，內容以食藥署公告為準。"


def _row(**values):
    base = dict.fromkeys(TFDA_COLUMNS, "")
    base.update(
        {
            "有效日期": "2027/01/31",
            "發證日期": "2020/01/01",
            "許可證種類": "09",
            "醫療器材級數": "2",
            "申請商名稱": "合成申請商股份有限公司",
            "申請商統一編號": "00012345",
            "製造商名稱": "Synthetic Maker One",
            "製造廠廠址": "1 Test Road",
            "製造廠國別": "DE",
            "異動日期": "2026/09/10",
        }
    )
    base.update(values)
    return [base[name] for name in TFDA_COLUMNS]


_HBA1C = {
    "許可證字號": FIRST,
    "中文品名": "“百得” 糖化血色素檢驗試劑",
    "英文品名": "Synthetic HbA1c Reagent",
    "效能": "定量血液中糖化血色素",
    "醫器主類別一": "B 血液學及病理學",
    "醫器次類別一": "B.9225 合成品項",
    "申請商名稱": "臺灣合成申請商股份有限公司",
}
ROWS = [
    _row(**_HBA1C, 醫器規格="第一行\r\n第二行"),  # 2 included
    _row(**_HBA1C, 製造商名稱="Synthetic Maker Two", 製造廠廠址="2 Test Road", 製造廠國別="US"),
    _row(  # 4 included, cancelled, validity elapsed
        許可證字號="衛部醫器製字第000002號",
        註銷狀態="已註銷",
        註銷日期="2025/05/01",
        註銷理由="合成測試理由",
        有效日期="2024/12/31",
        中文品名="糖化血色素分析儀",
        醫器主類別一="B 血液學及病理學",
        醫器次類別一="B.9225 合成品項",
    ),
    _row(  # 5 excluded
        許可證字號="衛署醫器輸字第000003號",
        中文品名="血液保存冰箱",
        醫器主類別一="B 血液學及病理學",
        醫器次類別一="B.9700 血液保存之冰箱與冷凍箱",
    ),
    _row(  # 6 unknown: category outside the reviewed annex
        許可證字號="衛部醫器輸字第000004號",
        中文品名="拋棄式軟性隱形眼鏡",
        效能="矯正視力",
        醫器主類別一="M 眼科學",
        醫器次類別一="M.5925 軟式隱形眼鏡",
    ),
    _row(  # 7 unknown: legacy numeric class, validity elapsed
        許可證字號="衛署醫器輸字第000005號",
        中文品名="糖化血色素試紙",
        有效日期="2020/01/01",
        醫器主類別一="4000 舊制主類別",
        醫器次類別一="4105 舊制品項",
    ),
    _row(  # 8 unknown: main class A alone never makes a row IVD
        許可證字號="衛部醫器輸字第000006號",
        中文品名="糖化血色素",
        醫器主類別一="A 臨床化學及臨床毒理學",
    ),
    _row(  # 9 included, query only in 效能
        許可證字號="衛部醫器輸字第000007號",
        中文品名="血糖機",
        效能="另可測糖化血色素",
        醫器主類別一="A 臨床化學及臨床毒理學",
        醫器次類別一="A.1345 葡萄糖試驗系統",
    ),
    _row(許可證字號="衛部醫器輸字第000008號", 中文品名="狀態矛盾測試品", 註銷狀態="暫停"),  # 10
]


def _zip_bytes(rows=ROWS):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(list(TFDA_COLUMNS))
    writer.writerows(rows)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("68_2.csv", (chr(0xFEFF) + buffer.getvalue()).encode("utf-8"))
    return archive.getvalue()


@pytest.fixture
def built(tmp_path):
    summary = build_tfda_snapshot(_zip_bytes(), tmp_path)
    return tmp_path, summary


def _adapter(data_root, when=datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)):
    adapter = TFDAAdapter(DataContext(mode="official_snapshot", data_root=data_root))
    adapter.context = DataContext(mode="official_snapshot", data_root=data_root, clock=lambda: when)
    return adapter


def _rows(result):
    return [item.evidence[0].locator.source_row_number for item in result.items]


def test_build_keeps_every_source_row_with_labels(built):
    data_root, summary = built
    assert summary["rows"] == 9
    db_path = data_root / "curated" / "tfda_devices" / summary["snapshot_id"] / "data.sqlite3"
    connection = sqlite3.connect(db_path)
    try:
        labels = dict(
            connection.execute(
                "SELECT source_row_number, ivd_scope FROM tfda_source_row ORDER BY source_row_number"
            ).fetchall()
        )
        classifications = connection.execute("SELECT COUNT(*) FROM tfda_classification").fetchone()
    finally:
        connection.close()
    assert labels == {
        2: "included",
        3: "included",
        4: "included",
        5: "excluded",
        6: "unknown",
        7: "unknown",
        8: "unknown",
        9: "included",
        10: "unknown",
    }
    # One classification row per ordinal that has a main or sub category value.
    assert classifications == (8,)


def test_list_matching_ranks_by_match_tier_then_blank_cancellation(built):
    result = _adapter(built[0]).list_matching_license_records("糖化血色素", 20)
    assert result.result_status == "ok"
    assert _rows(result) == [8, 7, 4, 2, 3, 9]
    assert result.total_matches == 6
    assert result.evaluated_as_of == date(2026, 9, 15)
    assert result.evaluated_timezone == "Asia/Taipei"
    record = result.items[3].record
    assert record.record_type == "tfda_device_summary"
    assert record.matched_by == ["name_zh", "effect"]
    assert record.license_no_raw == FIRST
    assert record.ivd_scope == "included"
    assert record.main_category_letters == ["B"]
    assert record.classification_codes == ["B.9225"]
    assert record.risk_class_raw == "2"
    assert record.license_kind_raw == "09"
    assert record.cancellation_recorded_in_source is False
    assert record.within_validity_period_as_of is True
    dumped = str(result.model_dump(mode="json")).lower()
    assert "score" not in dumped and "similar" not in dumped
    assert TFDA_NOT_OFFICIAL_NOTE in result.notes
    assert result.coverage_status == "review_incomplete"
    assert "coverage_review_incomplete" in result.warnings


def test_preferences_change_order_but_not_totals(built):
    adapter = _adapter(built[0])
    for kwargs in ({"prefer_ivd": True}, {"prefer_main_category": "B"}):
        result = adapter.list_matching_license_records("糖化血色素", 20, 0, **kwargs)
        assert _rows(result) == [8, 4, 7, 2, 3, 9], kwargs
        assert result.total_matches == 6


def test_filters_narrow_only_when_requested(built):
    adapter = _adapter(built[0])
    assert _rows(adapter.list_matching_license_records("糖化血色素", ivd_scope="included")) == [
        4,
        2,
        3,
        9,
    ]
    assert _rows(adapter.list_matching_license_records("糖化血色素", ivd_scope="unknown")) == [8, 7]
    assert _rows(adapter.list_matching_license_records("糖化血色素", main_category="A")) == [8, 9]
    excluded = adapter.list_matching_license_records("血液保存", ivd_scope="excluded")
    assert _rows(excluded) == [5]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 21},
        {"limit": 0},
        {"offset": -1},
        {"ivd_scope": "yes"},
        {"main_category": "Z"},
        {"main_category": "AB"},
        {"prefer_main_category": "b"},
        {"prefer_ivd": "true"},
    ],
)
def test_list_matching_rejects_invalid_parameters(built, kwargs):
    result = _adapter(built[0]).list_matching_license_records("糖化血色素", **kwargs)
    assert result.result_status == "invalid_request"
    assert result.data_mode == "official_snapshot"


def test_list_matching_pages_to_the_last_row(built):
    adapter = _adapter(built[0])
    first = adapter.list_matching_license_records("糖化血色素", 2, 0)
    last = adapter.list_matching_license_records("糖化血色素", 2, 4)
    beyond = adapter.list_matching_license_records("糖化血色素", 2, 6)
    assert (_rows(first), first.truncated, first.total_matches) == ([8, 7], True, 6)
    assert (_rows(last), last.truncated, last.total_matches) == ([3, 9], False, 6)
    assert (beyond.result_status, beyond.returned_count, beyond.total_matches) == (
        "not_found",
        0,
        6,
    )


def test_search_folds_quotes_and_tai_and_matches_two_characters(built):
    adapter = _adapter(built[0])
    quoted = adapter.list_matching_license_records('"百得"')
    assert _rows(quoted) == [2, 3]
    assert quoted.items[0].record.matched_by == ["name_zh"]
    applicant = adapter.list_matching_license_records("台灣合成申請商")
    assert _rows(applicant) == [2, 3]
    assert applicant.items[0].record.matched_by == ["applicant"]
    assert _rows(adapter.list_matching_license_records("隱形")) == [6]
    exact = adapter.list_matching_license_records(FIRST)
    assert _rows(exact)[:2] == [2, 3]
    assert exact.items[0].record.matched_by == ["license_no"]


def test_get_license_returns_every_manufacturing_row_in_full(built):
    result = _adapter(built[0]).get_license(FIRST)
    assert result.result_status == "ok"
    assert _rows(result) == [2, 3]
    first, second = (item.record for item in result.items)
    assert first.record_type == "tfda_device"
    assert [first.manufacturer_name_raw, second.manufacturer_name_raw] == [
        "Synthetic Maker One",
        "Synthetic Maker Two",
    ]
    assert first.applicant_name_raw == "臺灣合成申請商股份有限公司"
    assert first.applicant_tax_id_raw == "00012345"
    assert first.specification_raw == "第一行\r\n第二行"
    assert first.valid_through_raw == "2027/01/31"
    assert first.ivd_rule_version == "tfda-ivd-v1"
    assert result.evaluated_as_of == date(2026, 9, 15)


def test_validity_is_inclusive_and_changes_across_days_without_a_new_build(built):
    data_root, summary = built
    on_day = _adapter(data_root, datetime(2027, 1, 30, 16, 0, tzinfo=timezone.utc)).get_license(
        FIRST
    )
    next_day = _adapter(data_root, datetime(2027, 1, 31, 16, 0, tzinfo=timezone.utc)).get_license(
        FIRST
    )
    assert on_day.evaluated_as_of == date(2027, 1, 31)
    assert on_day.items[0].record.within_validity_period_as_of is True
    assert on_day.items[0].item_warnings == []
    assert next_day.evaluated_as_of == date(2027, 2, 1)
    assert next_day.items[0].record.within_validity_period_as_of is False
    assert next_day.items[0].item_warnings == ["validity_period_elapsed"]
    assert on_day.provenance.curated_build_id == next_day.provenance.curated_build_id
    assert on_day.provenance.curated_build_id == summary["snapshot_id"]


def test_cancelled_row_keeps_both_outputs_separate(built):
    item = _adapter(built[0]).get_license("衛部醫器製字第000002號").items[0]
    assert item.record.cancellation_recorded_in_source is True
    assert item.record.within_validity_period_as_of is False
    assert item.item_warnings == ["cancellation_recorded_and_validity_period_elapsed"]
    unknown = _adapter(built[0]).get_license("衛部醫器輸字第000008號").items[0]
    assert unknown.record.cancellation_recorded_in_source == "unknown"
    assert unknown.item_warnings == ["unknown_cancellation_status", "cancellation_record_ambiguous"]


AS_OF = date(2026, 9, 15)


@pytest.mark.parametrize(
    ("status", "cancelled_on", "valid_through", "expected"),
    [
        ("", None, date(2027, 1, 1), (False, True, [])),
        (" ", None, date(2026, 1, 1), (False, False, ["validity_period_elapsed"])),
        (
            "",
            date(2025, 1, 1),
            date(2027, 1, 1),
            (
                True,
                True,
                [
                    "cancellation_date_without_status",
                    "cancellation_recorded_within_validity_window",
                ],
            ),
        ),
        (
            "已註銷",
            date(2025, 1, 1),
            date(2026, 9, 15),
            (True, True, ["cancellation_recorded_within_validity_window"]),
        ),
        (
            "已廢止",
            None,
            date(2026, 9, 14),
            (
                True,
                False,
                [
                    "cancellation_status_without_date",
                    "cancellation_recorded_and_validity_period_elapsed",
                ],
            ),
        ),
        (
            "暫停",
            date(2025, 1, 1),
            date(2027, 1, 1),
            ("unknown", True, ["unknown_cancellation_status", "cancellation_record_ambiguous"]),
        ),
        (
            "暫停",
            None,
            date(2026, 1, 1),
            (
                "unknown",
                False,
                [
                    "unknown_cancellation_status",
                    "cancellation_record_ambiguous",
                    "validity_period_elapsed",
                ],
            ),
        ),
        (
            "暫停",
            None,
            None,
            (
                "unknown",
                "unknown",
                [
                    "unknown_cancellation_status",
                    "cancellation_record_ambiguous",
                    "validity_date_unavailable",
                ],
            ),
        ),
        ("", None, None, (False, "unknown", ["validity_date_unavailable"])),
    ],
)
def test_truth_table(status, cancelled_on, valid_through, expected):
    evaluation = evaluate_temporal(status, cancelled_on, valid_through, AS_OF)
    assert (
        evaluation.cancellation_recorded_in_source,
        evaluation.within_validity_period_as_of,
        evaluation.warnings,
    ) == expected


def test_find_manufacturer_never_matches_the_applicant(built):
    adapter = _adapter(built[0])
    result = adapter.find_manufacturer("Synthetic Maker Two")
    assert _rows(result) == [3]
    assert result.items[0].record.matched_by == ["manufacturer"]
    assert adapter.find_manufacturer("臺灣合成申請商").result_status == "not_found"


def test_reviewed_search_returns_only_included_rows(built):
    adapter = _adapter(built[0])
    reviewed = adapter.search_reviewed_ivd("糖化血色素")
    assert _rows(reviewed) == [4, 2, 3, 9]
    assert {item.record.ivd_scope for item in reviewed.items} == {"included"}
    with_maker = adapter.search_reviewed_ivd("糖化血色素", "Synthetic Maker Two")
    assert _rows(with_maker) == [3]
    assert adapter.search_reviewed_ivd("血液保存冰箱").result_status == "not_found"


def test_reviewed_search_points_to_candidates_instead_of_not_found(built):
    adapter = _adapter(built[0])
    for result in (adapter.search_reviewed_ivd("隱形眼鏡"), adapter.search_ivd("隱形眼鏡")):
        assert result.result_status == "candidate_matches_available"
        assert result.items == []
        assert result.evaluated_as_of == date(2026, 9, 15)
        assert any("search_ivd_candidates" in note for note in result.notes)


def test_candidate_search_excludes_excluded_rows_and_reports_coverage(built):
    result = _adapter(built[0]).search_ivd_candidates("糖化血色素")
    assert _rows(result) == [8, 7, 4, 2, 3, 9]
    assert result.coverage_detail == {
        "reviewed_codes": 3,
        "total_codes": 3,
        "legacy_code_rows": 1,
        "missing_code_rows": 2,
        "unknown_code_rows": 1,
        "rule_version": "tfda-ivd-v1",
    }
    blood = _adapter(built[0]).search_ivd_candidates("血液保存冰箱")
    assert blood.result_status == "not_found"


def test_search_tools_share_the_twenty_row_page_limit(built):
    adapter = _adapter(built[0])
    assert adapter.search_reviewed_ivd("糖化", None, 21).result_status == "invalid_request"
    assert adapter.search_ivd_candidates("糖化", None, 21).result_status == "invalid_request"
    assert adapter.search_ivd_candidates("糖化", None, 20).result_status == "ok"


def test_official_status_attribution_and_deprecated_compare(built):
    from taiwan_lab_mcp.stores import read_source_status

    data_root, summary = built
    status = read_source_status(
        data_root, "tfda_device", clock=lambda: datetime(2026, 9, 15, tzinfo=timezone.utc)
    )
    assert status.availability == "available"
    assert status.serving_curated_build_id == summary["snapshot_id"]
    assert status.coverage_status == "review_incomplete"
    assert read_source_status(data_root, "nhi_fee").availability == "data_unavailable"
    result = _adapter(data_root).get_license(FIRST)
    assert result.provenance.attribution.startswith("衛生福利部食品藥物管理署 ")
    assert "醫療器材許可證資料集" in result.provenance.attribution
    assert result.provenance.rule_bundle_version == "tfda-ivd-v1"
    compare = _adapter(data_root).compare_products("糖化血色素")
    assert compare.result_status == "deprecated_unsupported"
    assert compare.data_mode == "official_snapshot"


def test_tampered_database_is_not_served(built):
    data_root, summary = built
    adapter = _adapter(data_root)
    assert adapter.get_license(FIRST).result_status == "ok"
    db_path = data_root / "curated" / "tfda_devices" / summary["snapshot_id"] / "data.sqlite3"
    with db_path.open("ab") as stream:
        stream.write(b"tamper")
    result = adapter.get_license(FIRST)
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"
