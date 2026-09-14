import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from taiwan_lab_mcp.importers.tfda import TFDA_COLUMNS

_OID = "2.16.886.101.20003.20065.20065"
_CSV_URL = "https://data.fda.gov.tw/data/opendata/export/68/csv"


def _metadata_bytes(**overrides):
    result = {
        "publisherOID": _OID,
        "identifier": "A21020000I-000053",
        "license": "1",
        "modifiedDate": "2026-09-11 15:57:04",
        "distribution": [
            {
                "resourceFormat": "CSV",
                "resourceCharacterEncoding": "UTF-8",
                "resourceDownloadUrl": _CSV_URL,
            },
            {
                "resourceFormat": "JSON",
                "resourceCharacterEncoding": "UTF-8",
                "resourceDownloadUrl": "https://data.fda.gov.tw/data/opendata/export/68/json",
            },
        ],
    }
    result.update(overrides)
    return json.dumps({"success": True, "result": result}, ensure_ascii=False).encode("utf-8")


def _zip_bytes():
    row = {name: "" for name in TFDA_COLUMNS}
    row.update({"許可證字號": "衛部醫器輸字第000001號", "有效日期": "2027/01/31"})
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(TFDA_COLUMNS)
    writer.writerow([row[name] for name in TFDA_COLUMNS])
    payload = (chr(0xFEFF) + buffer.getvalue()).encode("utf-8")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("68_2.csv", payload)
    return archive.getvalue()


class _Headers(dict):
    def get_content_type(self):
        return self.get("Content-Type", "").split(";", 1)[0].strip().lower()


class _Response:
    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self.body = body
        self.headers = _Headers(headers or {})
        self.offset = 0

    def getcode(self):
        return self.status

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self.body) - self.offset
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self):
        pass


class _Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def open(self, request, timeout):
        self.urls.append(request.full_url)
        return self.responses.pop(0)


def _json(body):
    return _Response(200, body, {"Content-Type": "application/json"})


def _zip_response(body):
    return _Response(200, body, {"Content-Type": "application/zip"})


def _clock():
    return datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc)


def test_discover_tfda_resource_returns_owner_confirmed_identity():
    from taiwan_lab_mcp.tfda_source import discover_tfda_resource

    discovery = discover_tfda_resource(_metadata_bytes(), expected_publisher_oid=_OID)

    assert discovery == {
        "dataset_id": "9576",
        "identifier": "A21020000I-000053",
        "publisher_oid": _OID,
        "landing_url": "https://data.gov.tw/dataset/9576",
        "metadata_url": "https://data.gov.tw/api/v2/rest/dataset/9576",
        "license_code": "1",
        "license_name": "政府資料開放授權條款-第1版",
        "license_url": "https://data.gov.tw/license",
        "provider": "衛生福利部食品藥物管理署",
        "resource_format": "CSV",
        "resource_url": _CSV_URL,
        "official_modified_at_raw": "2026-09-11 15:57:04",
        "official_modified_timezone_known": False,
    }


@pytest.mark.parametrize(
    ("overrides", "expected_oid", "expected_code"),
    [
        ({}, "2.16.886.101.20003.20065.20022", "DISCOVERY_PUBLISHER_MISMATCH"),
        ({"identifier": "A21020000I-000054"}, _OID, "DISCOVERY_IDENTIFIER_MISMATCH"),
        ({"license": "2"}, _OID, "DISCOVERY_LICENSE_MISMATCH"),
        (
            {
                "distribution": [
                    {
                        "resourceFormat": "CSV",
                        "resourceCharacterEncoding": "UTF-8",
                        "resourceDownloadUrl": "https://example.com/68/csv",
                    }
                ]
            },
            _OID,
            "FETCH_HOST_NOT_ALLOWED",
        ),
        (
            {
                "distribution": [
                    {
                        "resourceFormat": "CSV",
                        "resourceCharacterEncoding": "UTF-8",
                        "resourceDownloadUrl": "http://data.fda.gov.tw/data/opendata/export/68/csv",
                    }
                ]
            },
            _OID,
            "FETCH_HOST_NOT_ALLOWED",
        ),
        ({"distribution": []}, _OID, "DISCOVERY_RESOURCE_MISSING"),
    ],
)
def test_discover_tfda_resource_rejects_identity_drift(overrides, expected_oid, expected_code):
    from taiwan_lab_mcp.fetch import FetchError
    from taiwan_lab_mcp.tfda_source import discover_tfda_resource

    with pytest.raises(FetchError) as error:
        discover_tfda_resource(_metadata_bytes(**overrides), expected_publisher_oid=expected_oid)
    assert error.value.code == expected_code


def test_tfda_upstream_sync_keeps_raw_zip_and_writes_validation_report(tmp_path):
    from taiwan_lab_mcp.canonical import sha256_bytes
    from taiwan_lab_mcp.tfda_source import run_tfda_upstream_sync

    archive = _zip_bytes()
    opener = _Opener(_json(_metadata_bytes()), _zip_response(archive))

    report = run_tfda_upstream_sync(
        tmp_path, expected_publisher_oid=_OID, opener=opener, clock=_clock
    )

    assert opener.urls == ["https://data.gov.tw/api/v2/rest/dataset/9576", _CSV_URL]
    assert report["status"] == "passed"
    assert report["stage"] == "validate"
    assert report["source_id"] == "tfda_devices"
    assert report["input_kind"] == "upstream"
    assert report["candidate_status"] == "none"
    assert report["summary"]["rows"] == 1
    raw_revision_id = report["raw_revision_id"]
    raw_dir = tmp_path / "raw" / "tfda_devices" / raw_revision_id
    assert (raw_dir / "artifacts" / "source.zip").read_bytes() == archive
    fetch_record = json.loads((raw_dir / "fetch.json").read_text(encoding="utf-8"))
    assert fetch_record["artifact"]["sha256"] == sha256_bytes(archive)
    assert fetch_record["artifact"]["final_url"] == _CSV_URL
    assert fetch_record["discovery"]["publisher_oid"] == _OID
    assert report["raw_artifact_data_root_relative_path"] == (
        f"raw/tfda_devices/{raw_revision_id}/artifacts/source.zip"
    )
    report_path = tmp_path / Path(report["report_data_root_relative_path"])
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    assert not (tmp_path / "manifests").exists()
    assert not (tmp_path / "curated").exists()


def test_tfda_upstream_sync_same_bytes_reuse_the_raw_revision(tmp_path):
    from taiwan_lab_mcp.tfda_source import run_tfda_upstream_sync

    archive = _zip_bytes()
    first = run_tfda_upstream_sync(
        tmp_path,
        expected_publisher_oid=_OID,
        opener=_Opener(_json(_metadata_bytes()), _zip_response(archive)),
        clock=_clock,
    )
    fetch_path = tmp_path / "raw" / "tfda_devices" / first["raw_revision_id"] / "fetch.json"
    fetch_before = fetch_path.read_bytes()

    second = run_tfda_upstream_sync(
        tmp_path,
        expected_publisher_oid=_OID,
        opener=_Opener(_json(_metadata_bytes()), _zip_response(archive)),
        clock=lambda: datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc),
    )

    assert second["status"] == "passed"
    assert second["raw_revision_id"] == first["raw_revision_id"]
    assert second["report_data_root_relative_path"] != first["report_data_root_relative_path"]
    assert fetch_path.read_bytes() == fetch_before


def test_tfda_upstream_sync_keeps_raw_when_the_download_is_not_a_valid_zip(tmp_path):
    from taiwan_lab_mcp.tfda_source import run_tfda_upstream_sync

    report = run_tfda_upstream_sync(
        tmp_path,
        expected_publisher_oid=_OID,
        opener=_Opener(_json(_metadata_bytes()), _zip_response(b"<html>maintenance</html>")),
        clock=_clock,
    )

    assert report["status"] == "failed"
    assert report["stage"] == "archive"
    assert report["error_code"] == "CONTENT_MAGIC_MISMATCH"
    assert report["raw_revision_id"] is not None
    assert (tmp_path / Path(report["raw_artifact_data_root_relative_path"])).is_file()


@pytest.mark.parametrize(
    ("responses", "expected_stage", "expected_code"),
    [
        (
            lambda: [_json(_metadata_bytes(publisherOID="2.16.886.101.20003.20065.20022"))],
            "discover",
            "DISCOVERY_PUBLISHER_MISMATCH",
        ),
        (
            lambda: [
                _json(_metadata_bytes()),
                _Response(503, b"down", {"Content-Type": "text/plain"}),
            ],
            "fetch",
            None,
        ),
    ],
)
def test_tfda_upstream_sync_failures_before_download_keep_no_raw(
    tmp_path, responses, expected_stage, expected_code
):
    from taiwan_lab_mcp.tfda_source import run_tfda_upstream_sync

    report = run_tfda_upstream_sync(
        tmp_path, expected_publisher_oid=_OID, opener=_Opener(*responses()), clock=_clock
    )

    assert report["status"] == "failed"
    assert report["stage"] == expected_stage
    if expected_code:
        assert report["error_code"] == expected_code
    assert report["error_code"]
    assert report["raw_revision_id"] is None
    assert not (tmp_path / "raw").exists()
    assert (tmp_path / Path(report["report_data_root_relative_path"])).is_file()


@pytest.mark.parametrize("failing_step", ["extract_tfda_csv", "summarize_tfda_csv"])
def test_tfda_upstream_sync_reports_memory_exhaustion_instead_of_crashing(
    tmp_path, monkeypatch, failing_step
):
    import taiwan_lab_mcp.tfda_source as tfda_source

    def exhausted(*args, **kwargs):
        raise MemoryError("Unable to allocate output buffer.")

    monkeypatch.setattr(tfda_source, failing_step, exhausted)
    archive = _zip_bytes()

    report = tfda_source.run_tfda_upstream_sync(
        tmp_path,
        expected_publisher_oid=_OID,
        opener=_Opener(_json(_metadata_bytes()), _zip_response(archive)),
        clock=_clock,
    )

    assert report["status"] == "failed"
    assert report["error_code"] == "RESOURCE_EXHAUSTED"
    assert report["stage"] == ("archive" if failing_step == "extract_tfda_csv" else "parse")
    assert (tmp_path / Path(report["raw_artifact_data_root_relative_path"])).read_bytes() == archive
    assert (tmp_path / Path(report["report_data_root_relative_path"])).is_file()


def test_cli_validate_tfda_reports_memory_exhaustion(tmp_path, monkeypatch, capsys):
    import taiwan_lab_mcp.importers.tfda as tfda_importer
    from taiwan_lab_mcp.data_cli import main

    def exhausted(*args, **kwargs):
        raise MemoryError("Unable to allocate output buffer.")

    monkeypatch.setattr(tfda_importer, "extract_tfda_csv", exhausted)
    archive_path = tmp_path / "68_csv.zip"
    archive_path.write_bytes(_zip_bytes())

    code = main(["validate", "tfda_devices", "--input", str(archive_path), "--json"])

    assert code == 4
    assert json.loads(capsys.readouterr().out) == {
        "source_id": "tfda_devices",
        "validation_status": "failed",
        "error_code": "RESOURCE_EXHAUSTED",
    }


def test_cli_sync_tfda_upstream_uses_explicit_publisher_oid(tmp_path, monkeypatch, capsys):
    import taiwan_lab_mcp.tfda_source as tfda_source
    from taiwan_lab_mcp.data_cli import main

    calls = []

    def fake_sync(data_root, *, expected_publisher_oid):
        calls.append((Path(data_root), expected_publisher_oid))
        return {"status": "failed", "stage": "fetch", "error_code": "FETCH_HTTP_STATUS"}

    monkeypatch.setattr(tfda_source, "run_tfda_upstream_sync", fake_sync)

    code = main(
        ["sync", "tfda_devices", "--publisher-oid", _OID, "--data-dir", str(tmp_path), "--json"]
    )

    assert code == 3
    assert calls == [(tmp_path, _OID)]
    assert json.loads(capsys.readouterr().out)["stage"] == "fetch"
