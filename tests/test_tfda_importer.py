import csv
import io
import json
import struct
import zipfile
from pathlib import Path

import pytest

from taiwan_lab_mcp.importers.tfda import (
    TFDA_COLUMNS,
    TFDAImportError,
    extract_tfda_csv,
    parse_tfda_csv,
)

# Header copied from docs/research/tfda-data-source.md section 5 (2026-09-13 CSV).
_RESEARCH_HEADER = (
    '"許可證字號","註銷狀態","註銷日期","註銷理由","有效日期","發證日期","許可證種類",'
    '"舊證字號","醫療器材級數","通關簽審文件編號","中文品名","英文品名","效能","劑型",'
    '"包裝","醫器主類別一","醫器次類別一","醫器主類別二","醫器次類別二","醫器主類別三",'
    '"醫器次類別三","主成分略述","醫器規格","限制項目","申請商名稱","申請商地址",'
    '"申請商統一編號","製造商名稱","製造廠廠址","製造廠公司地址","製造廠國別","製程",'
    '"異動日期","製造許可登錄編號"'
)


def _row(**values):
    base = {name: "" for name in TFDA_COLUMNS}
    base.update(
        {
            "許可證字號": "衛部醫器輸字第000001號",
            "有效日期": "2027/01/31",
            "發證日期": "2020/01/01",
            "許可證種類": "09",
            "醫療器材級數": "2",
            "中文品名": "合成測試試劑",
            "英文品名": "Synthetic Test Reagent",
            "醫器主類別一": "B 臨床化學及臨床毒理學",
            "醫器次類別一": "B.9225 合成測試品項",
            "申請商名稱": "合成申請商股份有限公司",
            "申請商統一編號": "00012345",
            "製造商名稱": "Synthetic Maker One",
            "製造廠廠址": "1 Test Road",
            "製造廠國別": "DE",
            "醫器規格": "第一行\r\n第二行",
            "異動日期": "2026/09/10",
        }
    )
    base.update(values)
    return [base[name] for name in TFDA_COLUMNS]


def _csv_bytes(rows, header=None, bom=True):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(list(header or TFDA_COLUMNS))
    for row in rows:
        writer.writerow(row)
    return ((chr(0xFEFF) if bom else "") + buffer.getvalue()).encode("utf-8")


def _default_rows():
    return [
        _row(),
        _row(製造商名稱="Synthetic Maker Two", 製造廠廠址="2 Test Road", 製造廠國別="US"),
        _row(
            許可證字號="衛部醫器製字第000002號",
            註銷狀態="已註銷",
            註銷日期="2025/05/01",
            註銷理由="合成測試理由",
            有效日期="2024/12/31",
        ),
    ]


def _zip(entries, compression=zipfile.ZIP_DEFLATED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for entry in entries:
            if isinstance(entry, zipfile.ZipInfo):
                archive.writestr(entry, b"" if entry.is_dir() else _csv_bytes(_default_rows()))
            else:
                name, payload = entry
                archive.writestr(name, payload)
    return buffer.getvalue()


def _valid_zip():
    return _zip([("68_2.csv", _csv_bytes(_default_rows()))])


def test_tfda_columns_match_research_header_exactly():
    assert tuple(next(csv.reader([_RESEARCH_HEADER]))) == TFDA_COLUMNS
    assert len(TFDA_COLUMNS) == 34


def test_tfda_zip_csv_preserves_every_source_row_as_strings():
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes

    archive = _valid_zip()
    entry = extract_tfda_csv(archive)

    assert entry.name == "68_2.csv"
    assert entry.zip_sha256 == sha256_bytes(archive)
    assert entry.payload_sha256 == sha256_bytes(entry.payload)
    assert entry.uncompressed_bytes == len(entry.payload)

    parsed = parse_tfda_csv(entry.payload)
    assert [row.source_row_number for row in parsed.rows] == [2, 3, 4]
    first = parsed.rows[0]
    assert first.values["申請商統一編號"] == "00012345"
    assert first.values["醫療器材級數"] == "2"
    assert first.values["許可證種類"] == "09"
    assert first.values["醫器規格"] == "第一行\r\n第二行"
    assert first.source_row_sha256 == sha256_bytes(canonical_json_bytes(_default_rows()[0]))
    # The permit number is a group key; both manufacturing rows stay.
    same_permit = [
        row for row in parsed.rows if row.values["許可證字號"] == "衛部醫器輸字第000001號"
    ]
    assert [row.values["製造商名稱"] for row in same_permit] == [
        "Synthetic Maker One",
        "Synthetic Maker Two",
    ]
    assert len({row.source_row_sha256 for row in parsed.rows}) == 3


def test_tfda_summary_reports_groups_status_and_empty_counts():
    from taiwan_lab_mcp.importers.tfda import tfda_validation_summary

    entry = extract_tfda_csv(_valid_zip())
    summary = tfda_validation_summary(entry, parse_tfda_csv(entry.payload))

    assert summary["rows"] == 3
    assert summary["distinct_license_numbers"] == 2
    assert summary["license_numbers_with_multiple_rows"] == 1
    assert summary["max_rows_per_license_number"] == 2
    assert summary["cancellation_status_counts"] == {"": 2, "已註銷": 1}
    assert summary["empty_value_counts"]["劑型"] == 3
    assert summary["empty_value_counts"]["許可證字號"] == 0
    assert summary["archive"] == {
        "zip_bytes": len(_valid_zip()),
        "zip_sha256": entry.zip_sha256,
        "entry_name": "68_2.csv",
        "entry_bytes": len(entry.payload),
        "entry_sha256": entry.payload_sha256,
    }


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (b"<!DOCTYPE html><html><body>error</body></html>", "CONTENT_MAGIC_MISMATCH"),
        ("許可證字號,註銷狀態\n".encode(), "CONTENT_MAGIC_MISMATCH"),
        (b"", "ARCHIVE_EMPTY"),
    ],
)
def test_tfda_payload_must_be_a_zip_by_magic_bytes(payload, expected_code):
    with pytest.raises(TFDAImportError) as error:
        extract_tfda_csv(payload)
    assert error.value.code == expected_code


def test_tfda_truncated_zip_is_blocked():
    archive = _valid_zip()
    with pytest.raises(TFDAImportError) as error:
        extract_tfda_csv(archive[: len(archive) // 2])
    assert error.value.code == "ARCHIVE_CORRUPT"


def _symlink_entry():
    info = zipfile.ZipInfo("68_2.csv")
    info.external_attr = (0o120777 << 16) | 0x20
    return info


@pytest.mark.parametrize(
    ("entries", "expected_code"),
    [
        ([("68_2.csv", b"a"), ("extra.csv", b"b")], "ARCHIVE_ENTRY_COUNT"),
        ([zipfile.ZipInfo("folder/"), ("folder/68_2.csv", b"a")], "ARCHIVE_ENTRY_COUNT"),
        ([zipfile.ZipInfo("folder/")], "ARCHIVE_ENTRY_TYPE"),
        ([("68_2.json", b"[]")], "ARCHIVE_ENTRY_TYPE"),
        ([_symlink_entry()], "ARCHIVE_ENTRY_TYPE"),
        ([("../68_2.csv", b"a")], "ARCHIVE_PATH_TRAVERSAL"),
        ([("safe/../../68_2.csv", b"a")], "ARCHIVE_PATH_TRAVERSAL"),
        ([("/abs/68_2.csv", b"a")], "ARCHIVE_PATH_TRAVERSAL"),
        ([("C:/data/68_2.csv", b"a")], "ARCHIVE_PATH_TRAVERSAL"),
        ([("//server/share/68_2.csv", b"a")], "ARCHIVE_PATH_TRAVERSAL"),
    ],
)
def test_tfda_zip_entry_rules(entries, expected_code):
    with pytest.raises(TFDAImportError) as error:
        extract_tfda_csv(_zip(entries))
    assert error.value.code == expected_code


def test_tfda_zip_backslash_paths_are_checked_after_normalization():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("placeholder.csv")
        archive.writestr(info, b"a")
    # Rewrite the stored name (same byte length) so the archive really contains
    # backslashes on every OS.
    raw = buffer.getvalue().replace(b"placeholder.csv", b"..\\aaaaaa\\x.csv")
    with pytest.raises(TFDAImportError) as error:
        extract_tfda_csv(raw)
    assert error.value.code == "ARCHIVE_PATH_TRAVERSAL"


def test_tfda_uncompressed_limit_counts_actual_streamed_bytes():
    archive = _valid_zip()
    payload_size = len(_csv_bytes(_default_rows()))

    assert extract_tfda_csv(archive, max_uncompressed_bytes=payload_size).uncompressed_bytes == (
        payload_size
    )
    with pytest.raises(TFDAImportError) as error:
        extract_tfda_csv(archive, max_uncompressed_bytes=payload_size - 1)
    assert error.value.code == "ARCHIVE_SIZE_LIMIT"


def test_tfda_compressed_size_limit():
    archive = _valid_zip()
    assert extract_tfda_csv(archive, max_zip_bytes=len(archive)).name == "68_2.csv"
    with pytest.raises(TFDAImportError) as error:
        extract_tfda_csv(archive, max_zip_bytes=len(archive) - 1)
    assert error.value.code == "ARCHIVE_SIZE_LIMIT"


def test_tfda_compression_ratio_limit():
    repetitive = _csv_bytes([_row() for _ in range(400)])
    archive = _zip([("68_2.csv", repetitive)])
    info = zipfile.ZipFile(io.BytesIO(archive)).infolist()[0]
    assert info.file_size / info.compress_size > 30

    with pytest.raises(TFDAImportError) as error:
        extract_tfda_csv(archive)
    assert error.value.code == "ARCHIVE_RATIO_LIMIT"
    assert extract_tfda_csv(archive, max_ratio=1000).name == "68_2.csv"


def test_tfda_declared_size_spoofing_is_rejected():
    archive = bytearray(_zip([("68_2.csv", _csv_bytes(_default_rows()))]))
    info = zipfile.ZipFile(io.BytesIO(bytes(archive))).infolist()[0]
    fake_size = info.file_size - 10
    # Local file header: uncompressed size at offset 22.
    struct.pack_into("<I", archive, 22, fake_size)
    central = bytes(archive).rfind(b"PK\x01\x02")
    struct.pack_into("<I", archive, central + 24, fake_size)

    with pytest.raises(TFDAImportError) as error:
        extract_tfda_csv(bytes(archive), max_uncompressed_bytes=info.file_size)
    assert error.value.code == "ARCHIVE_CORRUPT"


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (b"", "EMPTY_INPUT"),
        (_csv_bytes(_default_rows()).replace("合成".encode(), b"\x00", 1), "NUL_BYTE"),
        (b"\xef\xbb\xbf\xff\xfe", "DECODE_ERROR"),
        (_csv_bytes([]), "ZERO_ROWS"),
        (
            _csv_bytes(_default_rows(), header=[*TFDA_COLUMNS[:-1], "製造許可編號"]),
            "SCHEMA_HEADER_MISMATCH",
        ),
        (
            _csv_bytes(
                _default_rows(), header=[TFDA_COLUMNS[1], TFDA_COLUMNS[0], *TFDA_COLUMNS[2:]]
            ),
            "SCHEMA_HEADER_MISMATCH",
        ),
        (_csv_bytes(_default_rows(), header=TFDA_COLUMNS[:-1]), "SCHEMA_HEADER_MISMATCH"),
        (
            _csv_bytes(_default_rows(), header=[*TFDA_COLUMNS[:-1], TFDA_COLUMNS[0]]),
            "SCHEMA_DUPLICATE_COLUMN",
        ),
        (_csv_bytes([_row()[:-1]]), "ROW_WIDTH_MISMATCH"),
        (_csv_bytes([_row(), list(TFDA_COLUMNS)]), "SCHEMA_DUPLICATE_HEADER"),
        (_csv_bytes([_row(許可證字號="  ")]), "REQUIRED_VALUE_MISSING"),
        (_csv_bytes([_row(有效日期="")]), "REQUIRED_VALUE_MISSING"),
        (_csv_bytes([_row(有效日期="2027-01-31")]), "DATE_INVALID"),
        (_csv_bytes([_row(發證日期="2027/02/30")]), "DATE_INVALID"),
        (_csv_bytes([_row(註銷日期="2025/5/1")]), "DATE_INVALID"),
        (_csv_bytes([_row(異動日期=" 2026/09/10")]), "DATE_INVALID"),
    ],
)
def test_tfda_csv_schema_and_value_failures_block_the_batch(payload, expected_code):
    with pytest.raises(TFDAImportError) as error:
        parse_tfda_csv(payload)
    assert error.value.code == expected_code


def test_tfda_empty_optional_dates_and_missing_bom_warning():
    parsed = parse_tfda_csv(_csv_bytes([_row(註銷日期="", 異動日期="")], bom=False))

    assert parsed.rows[0].values["註銷日期"] == ""
    assert parsed.warnings == ("UTF8_BOM_ABSENT",)


def test_tfda_offline_validation_writes_only_a_staged_report(tmp_path):
    from taiwan_lab_mcp.importers.tfda import run_tfda_offline_validation

    report = run_tfda_offline_validation(_valid_zip(), tmp_path)

    assert report["status"] == "passed"
    assert report["source_id"] == "tfda_devices"
    assert report["stage"] == "validate"
    assert report["error_code"] is None
    assert report["candidate_status"] == "none"
    assert report["summary"]["rows"] == 3
    report_path = tmp_path / Path(report["report_data_root_relative_path"])
    assert report_path.parts[-4:-2] == ("staged", "tfda_devices")
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "curated").exists()
    assert not (tmp_path / "manifests").exists()
    assert str(tmp_path) not in report_path.read_text(encoding="utf-8")


def test_tfda_offline_validation_records_archive_failure(tmp_path):
    from taiwan_lab_mcp.importers.tfda import run_tfda_offline_validation

    report = run_tfda_offline_validation(b"<html>maintenance</html>", tmp_path)

    assert report["status"] == "failed"
    assert report["stage"] == "archive"
    assert report["error_code"] == "CONTENT_MAGIC_MISMATCH"
    assert report["blocking_errors"] == ["CONTENT_MAGIC_MISMATCH"]
    assert report["summary"] is None
    assert (tmp_path / Path(report["report_data_root_relative_path"])).is_file()


def test_cli_validate_and_sync_tfda_offline_zip(tmp_path, capsys):
    from taiwan_lab_mcp.data_cli import main

    archive_path = tmp_path / "68_csv.zip"
    archive_path.write_bytes(_valid_zip())
    bad_path = tmp_path / "bad.zip"
    bad_path.write_bytes(b"<html></html>")

    assert main(["validate", "tfda_devices", "--input", str(archive_path), "--json"]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["validation_status"] == "passed"
    assert validated["summary"]["rows"] == 3

    assert main(["validate", "tfda_devices", "--input", str(bad_path), "--json"]) == 4
    assert json.loads(capsys.readouterr().out) == {
        "source_id": "tfda_devices",
        "validation_status": "failed",
        "error_code": "CONTENT_MAGIC_MISMATCH",
    }

    data_root = tmp_path / "data"
    assert (
        main(
            [
                "sync",
                "tfda_devices",
                "--input",
                str(archive_path),
                "--data-dir",
                str(data_root),
                "--json",
            ]
        )
        == 0
    )
    synced = json.loads(capsys.readouterr().out)
    assert synced["status"] == "passed"
    assert (data_root / Path(synced["report_data_root_relative_path"])).is_file()

    # Offline input and upstream discovery are mutually exclusive, like NHI.
    with pytest.raises(SystemExit):
        main(
            [
                "sync",
                "tfda_devices",
                "--input",
                str(archive_path),
                "--publisher-oid",
                "unused",
                "--data-dir",
                str(data_root),
            ]
        )
