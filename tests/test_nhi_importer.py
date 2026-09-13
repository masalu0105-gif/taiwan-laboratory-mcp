import pytest

from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, NHIImportError, parse_nhi_csv


def _payload(row: str) -> bytes:
    return ("\ufeff" + ",".join(NHI_COLUMNS) + "\r\n" + row + "\r\n").encode("utf-8")


def test_nhi_01_exact_code_preserves_raw_fields_and_locator():
    result = parse_nhi_csv(_payload("09006C,12,20120101,29101231,HbA1c,醣化血紅素,完整備註"))

    row = result.rows[0]
    assert row.source_row_number == 2
    assert row.source_row_sha256
    assert row.code_raw == "09006C"
    assert row.code_normalized == "09006c"
    assert row.points_raw == "12"
    assert row.effective_start_raw == "20120101"
    assert row.effective_end_raw == "29101231"
    assert row.name_en_raw == "HbA1c"
    assert row.name_zh_raw == "醣化血紅素"
    assert row.note_raw == "完整備註"


def test_nhi_03_zero_points_and_full_note_are_preserved():
    result = parse_nhi_csv(_payload('09007C,0,20200101,29101231,Glucose,葡萄糖,"第一行\r\n第二行"'))

    row = result.rows[0]
    assert row.points == 0
    assert row.points_raw == "0"
    assert row.note_raw == "第一行\r\n第二行"
    assert row.to_record().points == 0
    assert row.to_record().note_raw == "第一行\r\n第二行"


def test_nhi_05_sentinel_stays_raw_inference_and_not_permanent():
    result = parse_nhi_csv(_payload("09008C,1,20200101,29101231,TSH,甲狀腺刺激素,"))

    row = result.rows[0]
    assert row.effective_end_raw == "29101231"
    assert row.effective_end == "2910-12-31"
    assert row.possible_open_end_sentinel is True
    assert "permanent" not in row.to_record().model_dump(mode="json")


def test_sdd_nhi_01_contract_bundle():
    result = parse_nhi_csv(_payload("09009C,3,20240101,20251231,Albumin,白蛋白,只保留來源原文"))

    assert len(result.rows) == 1
    assert len(NHI_COLUMNS) == 7
    assert result.rows[0].to_record().model_dump(mode="json")["points"] == 3


def test_nhi_points_overflow_returns_stable_import_error():
    huge_points = "9" * 5000

    with pytest.raises(NHIImportError, match="POINTS_INVALID"):
        parse_nhi_csv(_payload(f"09010C,{huge_points},20240101,20251231,Albumin,白蛋白,"))


def test_nhi_points_require_ascii_decimal_digits():
    with pytest.raises(NHIImportError, match="POINTS_INVALID"):
        parse_nhi_csv(_payload("09011C,１２,20240101,20251231,Albumin,白蛋白,"))
