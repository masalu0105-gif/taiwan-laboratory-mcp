"""Owner 2026-09-15 (OD-10): the GitHub Release download bundle also carries TFDA permits."""

import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

import taiwan_lab_mcp.importers.nhi as nhi_importer
from taiwan_lab_mcp.importers.tfda import TFDA_COLUMNS, build_tfda_snapshot

OID = "2.16.886.101.20003.20065.20065"
CLOCK = datetime(2026, 9, 18, 1, 30, tzinfo=timezone.utc)
CHANGED_PERMIT = "衛部醫器輸字第000012號"


def _row(number, **values):
    base = dict.fromkeys(TFDA_COLUMNS, "")
    base.update(
        {
            "許可證字號": f"衛部醫器輸字第{number:06d}號",
            "有效日期": "2027/01/31",
            "中文品名": f"合成品項{number}",
            "英文品名": f"Synthetic item {number}",
            "醫器主類別一": "B 血液學及病理學",
            "醫器次類別一": "B.9225 合成品項",
            "申請商名稱": "合成申請商股份有限公司",
            "製造商名稱": "Synthetic Maker",
            "醫療器材級數": "2",
        }
    )
    base.update(values)
    return [base[name] for name in TFDA_COLUMNS]


ROWS = [_row(number) for number in range(1, 13)]


def _zip(rows):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(list(TFDA_COLUMNS))
    writer.writerows(rows)
    archive = io.BytesIO()
    entry = zipfile.ZipInfo("68_2.csv", date_time=(2026, 9, 11, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(entry, (chr(0xFEFF) + buffer.getvalue()).encode("utf-8"))
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

    def open(self, request, timeout):
        return self.responses.pop(0)


def _metadata():
    body = {
        "success": True,
        "result": {
            "publisherOID": OID,
            "identifier": "A21020000I-000053",
            "license": "1",
            "modifiedDate": "2026-09-18 15:00:00",
            "distribution": [
                {
                    "resourceFormat": "CSV",
                    "resourceCharacterEncoding": "UTF-8",
                    "resourceDownloadUrl": "https://data.fda.gov.tw/data/opendata/export/68/csv",
                }
            ],
        },
    }
    return _Response(
        200, json.dumps(body, ensure_ascii=False).encode(), {"Content-Type": "application/json"}
    )


@pytest.fixture
def distribution(monkeypatch):
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("distribution", "d" * 64)
    )


def _serve_official(data_root):
    """Serve an official TFDA build published by the automatic update path."""

    from taiwan_lab_mcp.tfda_autoupdate import run_tfda_auto_update

    build_tfda_snapshot(_zip(ROWS), data_root)
    payload = _zip(ROWS[:-1] + [_row(12, 中文品名="改過的品名")])
    summary = run_tfda_auto_update(
        data_root,
        expected_publisher_oid=OID,
        actor="unit-test-auto-update",
        opener=_Opener(_metadata(), _Response(200, payload, {"Content-Type": "application/zip"})),
        clock=lambda: CLOCK,
    )
    assert summary["result"] == "published"
    return summary


def _descriptor(data_root):
    return json.loads((data_root / "manifests" / "current" / "tfda_devices.json").read_bytes())


def _export(data_root, output_dir):
    from taiwan_lab_mcp.snapshot_bundle import export_snapshot_bundle

    return export_snapshot_bundle(data_root, "tfda_devices", output_dir=output_dir)


def test_export_packs_the_tfda_raw_zip_and_curated_build(tmp_path, distribution):
    from taiwan_lab_mcp.canonical import sha256_bytes

    source_root = tmp_path / "source"
    summary = _serve_official(source_root)
    snapshot_id = summary["published_snapshot_id"]
    raw_revision_id = summary["candidate_raw_revision_id"]

    exported = _export(source_root, tmp_path / "release")

    bundle_path = Path(exported["bundle_path"])
    assert exported["snapshot_id"] == snapshot_id
    assert bundle_path.name == f"tfda_devices-snapshot-{snapshot_id[-64:][:12]}.zip"
    assert sha256_bytes(bundle_path.read_bytes()) == exported["bundle_sha256"]
    with zipfile.ZipFile(bundle_path) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("bundle-manifest.json"))
        for item in manifest["files"]:
            assert sha256_bytes(archive.read(item["path"])) == item["sha256"]
    assert f"raw/tfda_devices/{raw_revision_id}/artifacts/source.zip" in names
    assert f"raw/tfda_devices/{raw_revision_id}/fetch.json" in names
    assert f"curated/tfda_devices/{snapshot_id}/data.sqlite3" in names
    assert any(
        name.startswith(f"curated/tfda_devices/{snapshot_id}/audit/reviews/") for name in names
    )
    assert manifest["source_id"] == "tfda_devices"
    assert manifest["attribution"] == "資料提供機關：衛生福利部食品藥物管理署"
    assert "非食藥署官方服務" in manifest["notice"]

    # The same serving build exports to the same bytes.
    again = _export(source_root, tmp_path / "release-again")
    assert again["bundle_sha256"] == exported["bundle_sha256"]


def test_install_tfda_bundle_serves_the_same_permits(tmp_path, distribution):
    from taiwan_lab_mcp.adapters.tfda import TFDAAdapter
    from taiwan_lab_mcp.config import DataContext
    from taiwan_lab_mcp.snapshot_bundle import install_snapshot_bundle

    source_root = tmp_path / "source"
    summary = _serve_official(source_root)
    exported = _export(source_root, tmp_path / "release")
    user_root = tmp_path / "user-data"

    installed = install_snapshot_bundle(
        user_root,
        source_id="tfda_devices",
        bundle_path=Path(exported["bundle_path"]),
        expected_sha256=exported["bundle_sha256"],
        actor="unit-test-installer",
    )

    assert (installed["result"], installed["generation"]) == ("installed", 1)
    descriptor = _descriptor(user_root)
    assert descriptor["serving_snapshot_id"] == summary["published_snapshot_id"]
    assert descriptor["freshness_policy_version"] == "tfda-v1"
    assert (
        descriptor["last_successful_check_at"]
        == _descriptor(source_root)["last_successful_check_at"]
    )
    checked = datetime.fromisoformat(descriptor["last_successful_check_at"].replace("Z", "+00:00"))
    adapter = TFDAAdapter(
        DataContext(mode="official_snapshot", data_root=user_root, clock=lambda: checked)
    )
    result = adapter.get_license(CHANGED_PERMIT)
    assert result.result_status == "ok"
    assert result.items[0].record.name_zh_raw == "改過的品名"
    assert result.provenance.snapshot_id == summary["published_snapshot_id"]
    assert result.provenance.stale is False

    again = install_snapshot_bundle(
        user_root,
        source_id="tfda_devices",
        bundle_path=Path(exported["bundle_path"]),
        actor="unit-test-installer",
    )
    assert again["result"] == "already_installed"


def test_install_refuses_a_bundle_of_another_source_before_writing(tmp_path, distribution):
    from taiwan_lab_mcp.snapshot_bundle import SnapshotBundleError, install_snapshot_bundle

    source_root = tmp_path / "source"
    _serve_official(source_root)
    exported = _export(source_root, tmp_path / "release")
    user_root = tmp_path / "user-data"

    with pytest.raises(SnapshotBundleError) as error:
        install_snapshot_bundle(
            user_root,
            source_id="nhi_fee",
            bundle_path=Path(exported["bundle_path"]),
            actor="unit-test-installer",
        )

    assert error.value.code == "BUNDLE_SOURCE_MISMATCH"
    assert not user_root.exists()


def test_bundle_limits_fit_the_tfda_database():
    from taiwan_lab_mcp.snapshot_bundle import MAX_BUNDLE_BYTES, MAX_BUNDLE_UNCOMPRESSED_BYTES

    # 2026-09-15 launch build: 166,920,192-byte database (about 48.5 MB compressed) plus a
    # 16,265,433-byte raw ZIP.
    assert MAX_BUNDLE_BYTES == 128 * 1024 * 1024
    assert MAX_BUNDLE_UNCOMPRESSED_BYTES == 512 * 1024 * 1024


def test_cli_export_and_install_tfda_snapshot(tmp_path, distribution, capsys):
    from taiwan_lab_mcp.data_cli import main

    source_root = tmp_path / "source"
    _serve_official(source_root)
    capsys.readouterr()
    export_args = ["export-snapshot", "tfda_devices", "--data-dir", str(source_root)]
    assert main([*export_args, "--output-dir", str(tmp_path / "release"), "--json"]) == 0
    exported = json.loads(capsys.readouterr().out)

    def install(source_id):
        return main(
            [
                "install-snapshot",
                source_id,
                "--bundle",
                exported["bundle_path"],
                "--sha256",
                exported["bundle_sha256"],
                "--actor",
                "unit-test-installer",
                "--data-dir",
                str(tmp_path / "user-data"),
                "--json",
            ]
        )

    assert install("nhi_fee") == 4
    assert json.loads(capsys.readouterr().out)["error_code"] == "BUNDLE_SOURCE_MISMATCH"
    assert install("tfda_devices") == 0
    assert json.loads(capsys.readouterr().out)["result"] == "installed"
