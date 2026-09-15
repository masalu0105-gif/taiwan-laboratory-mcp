"""Owner 2026-09-15 chose automatic TFDA updates: checked new versions publish without a person."""

import csv
import io
import json
import zipfile
from datetime import datetime, timezone

import pytest

import taiwan_lab_mcp.importers.nhi as nhi_importer
from taiwan_lab_mcp.adapters.tfda import TFDAAdapter
from taiwan_lab_mcp.config import DataContext
from taiwan_lab_mcp.importers.tfda import TFDA_COLUMNS, build_tfda_snapshot

OID = "2.16.886.101.20003.20065.20065"
CLOCK = datetime(2026, 9, 18, 1, 30, tzinfo=timezone.utc)


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


def _auto(data_root, payload):
    from taiwan_lab_mcp.tfda_autoupdate import run_tfda_auto_update

    return run_tfda_auto_update(
        data_root,
        expected_publisher_oid=OID,
        actor="unit-test-auto-update",
        opener=_Opener(_metadata(), _Response(200, payload, {"Content-Type": "application/zip"})),
        clock=lambda: CLOCK,
    )


def _descriptor(data_root):
    return json.loads((data_root / "manifests" / "current" / "tfda_devices.json").read_bytes())


def _builds(data_root):
    return sorted(path.name for path in (data_root / "curated" / "tfda_devices").iterdir())


def test_same_version_needs_no_publish(tmp_path, distribution):
    build_tfda_snapshot(_zip(ROWS), tmp_path)
    summary = _auto(tmp_path, _zip(ROWS))
    assert summary["result"] == "unchanged"
    assert len(_builds(tmp_path)) == 1


def test_checked_new_version_is_published_automatically(tmp_path, distribution):
    build_tfda_snapshot(_zip(ROWS), tmp_path)
    before = _descriptor(tmp_path)
    new_rows = ROWS[:-1] + [_row(12, 中文品名="改過的品名")]

    summary = _auto(tmp_path, _zip(new_rows))

    assert summary["result"] == "published"
    assert summary["already_reported"] is False
    after = _descriptor(tmp_path)
    assert after["serving_snapshot_id"] == summary["published_snapshot_id"]
    assert after["serving_snapshot_id"] != before["serving_snapshot_id"]
    assert (after["stale"], after["latest_candidate_status"]) == (False, "none")
    build_dir = tmp_path / "curated" / "tfda_devices" / summary["published_snapshot_id"]
    review = json.loads((build_dir / "audit" / "reviews" / "PUB-R1-OWNER.json").read_bytes())
    assert review["reviewer_id"] == "automated-check:tfda-auto-update"
    assert review["reviewer_role"] == "automated_checker_delegated_by_owner"
    assert (review["protocol_id"], review["protocol_version"]) == ("tfda-r1-auto-review", "2")
    assert any(ref["artifact_id"] == "tfda-auto-roundtrip" for ref in review["evidence_refs"])
    certificate = json.loads((build_dir / "audit" / "golden-qualification.json").read_bytes())
    assert len(certificate["approved_distinct_case_ids"]) >= 10
    assert (tmp_path / summary["diff_summary_data_root_relative_path"]).is_file()

    adapter = TFDAAdapter(DataContext(mode="official_snapshot", data_root=tmp_path))
    record = adapter.get_license("衛部醫器輸字第000012號").items[0].record
    assert record.name_zh_raw == "改過的品名"


def test_unreviewed_annex_code_counts_as_ivd_and_is_listed(tmp_path, distribution):
    # Owner 2026-09-15 chose to count a new, not yet reviewed A/B/C code as IVD.
    build_tfda_snapshot(_zip(ROWS), tmp_path)
    new_rows = ROWS[:-1] + [_row(12, 醫器次類別一="A.5555 新增合成品項")]

    summary = _auto(tmp_path, _zip(new_rows))

    assert summary["result"] == "published"
    assert summary["unreviewed_annex_codes"] == ["A.5555"]
    adapter = TFDAAdapter(DataContext(mode="official_snapshot", data_root=tmp_path))
    record = adapter.get_license("衛部醫器輸字第000012號").items[0].record
    assert (record.classification_codes, record.ivd_scope) == (["A.5555"], "included")


def test_large_change_is_held_back_and_reported_once(tmp_path, distribution):
    build_tfda_snapshot(_zip(ROWS), tmp_path)
    before = _descriptor(tmp_path)
    smaller = _zip(ROWS[:10])

    first = _auto(tmp_path, smaller)
    assert first["result"] == "blocked"
    assert "row_count_change_exceeds_10_percent" in first["block_reasons"]
    assert first["already_reported"] is False
    after = _descriptor(tmp_path)
    assert after["serving_snapshot_id"] == before["serving_snapshot_id"]
    assert after["latest_candidate_status"] == "review_pending"

    second = _auto(tmp_path, smaller)
    assert (second["result"], second["already_reported"]) == ("blocked", True)
    assert len(_builds(tmp_path)) == 1


def test_new_cancellation_status_value_is_held_back(tmp_path, distribution):
    build_tfda_snapshot(_zip(ROWS), tmp_path)
    summary = _auto(tmp_path, _zip(ROWS[:-1] + [_row(12, 註銷狀態="暫停")]))
    assert summary["result"] == "blocked"
    assert "new_cancellation_status:暫停" in summary["block_reasons"]


def test_failed_full_table_check_keeps_the_old_version(tmp_path, distribution, monkeypatch):
    import taiwan_lab_mcp.tfda_autoupdate as autoupdate

    def broken(*args, **kwargs):
        raise autoupdate.AutoUpdateError("ROUNDTRIP_MISMATCH")

    monkeypatch.setattr(autoupdate, "verify_curated_roundtrip", broken)
    build_tfda_snapshot(_zip(ROWS), tmp_path)
    before = _descriptor(tmp_path)
    summary = _auto(tmp_path, _zip(ROWS[:-1] + [_row(12, 中文品名="改過的品名")]))
    assert (summary["result"], summary["error_code"]) == (
        "auto_publish_failed",
        "ROUNDTRIP_MISMATCH",
    )
    assert _descriptor(tmp_path)["serving_snapshot_id"] == before["serving_snapshot_id"]


def test_development_install_never_auto_publishes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("development", "d" * 64)
    )
    build_tfda_snapshot(_zip(ROWS), tmp_path)
    before = _descriptor(tmp_path)
    summary = _auto(tmp_path, _zip(ROWS[:-1] + [_row(12, 中文品名="改過的品名")]))
    assert (summary["result"], summary["error_code"]) == (
        "auto_publish_failed",
        "APPLICATION_BUILD_IDENTITY_MISSING",
    )
    assert _descriptor(tmp_path)["serving_snapshot_id"] == before["serving_snapshot_id"]


def test_independent_checks_agree_with_the_curated_build(tmp_path):
    from taiwan_lab_mcp.rules.tfda import packaged_ivd_registry_bytes
    from taiwan_lab_mcp.tfda_autoupdate import verify_curated_roundtrip

    payload = _zip(ROWS)
    built = build_tfda_snapshot(payload, tmp_path)
    db_path = tmp_path / "curated" / "tfda_devices" / built["snapshot_id"] / "data.sqlite3"
    report = verify_curated_roundtrip(db_path, payload, packaged_ivd_registry_bytes())
    assert (report["result"], report["rows_compared"]) == ("passed", 12)


def test_cli_auto_publish_routes_tfda(tmp_path, monkeypatch, capsys):
    import taiwan_lab_mcp.data_cli as data_cli

    calls = []

    def fake(data_root, **kwargs):
        calls.append((data_root, kwargs))
        return {"result": "published", "failed_stage": None, "error_code": None}

    monkeypatch.setattr("taiwan_lab_mcp.tfda_autoupdate.run_tfda_auto_update", fake)
    arguments = ["--publisher-oid", OID, "--actor", "unit-test", "--data-dir", str(tmp_path)]
    assert data_cli.main(["check", "tfda_devices", *arguments, "--auto-publish", "--json"]) == 0
    assert calls == [(tmp_path, {"expected_publisher_oid": OID, "actor": "unit-test"})]
    assert json.loads(capsys.readouterr().out)["result"] == "published"


def test_renewal_with_the_same_row_count_is_published(tmp_path, distribution):
    build_tfda_snapshot(_zip(ROWS), tmp_path)
    renewed = [list(row) for row in ROWS]
    renewed[4][TFDA_COLUMNS.index("有效日期")] = "2032/01/31"
    summary = _auto(tmp_path, _zip(renewed))
    assert summary["result"] == "published"
    diff = json.loads((tmp_path / summary["diff_data_root_relative_path"]).read_bytes())
    assert diff["validity_extended_permits"] == ["衛部醫器輸字第000005號"]
    adapter = TFDAAdapter(DataContext(mode="official_snapshot", data_root=tmp_path))
    adapter.context = DataContext(mode="official_snapshot", data_root=tmp_path, clock=lambda: CLOCK)
    record = adapter.get_license("衛部醫器輸字第000005號").items[0].record
    assert (record.valid_through_raw, record.within_validity_period_as_of) == ("2032/01/31", True)


def _version(number):
    rows = [list(row) for row in ROWS]
    rows[0][TFDA_COLUMNS.index("中文品名")] = f"第{number}版品名"
    return _zip(rows)


def test_retention_plan_keeps_three_versions_and_the_pending_candidate(tmp_path, distribution):
    from taiwan_lab_mcp.tfda_autoupdate import plan_tfda_retention

    first = build_tfda_snapshot(_zip(ROWS), tmp_path)
    published = [_auto(tmp_path, _version(number)) for number in (2, 3, 4)]
    assert [item["result"] for item in published] == ["published"] * 3
    held = _auto(tmp_path, _zip(ROWS[:9]))
    assert held["result"] == "blocked"
    orphan = tmp_path / "curated" / "tfda_devices" / ("tfda_devices-build-" + "e" * 64)
    orphan.mkdir()

    plan = plan_tfda_retention(tmp_path, keep_versions=3)

    newest = [item["published_snapshot_id"] for item in reversed(published)]
    assert plan["serving_snapshot_id"] == newest[0]
    assert plan["keep_builds"] == newest
    assert plan["remove_paths"] == sorted(
        [
            f"curated/tfda_devices/{first['snapshot_id']}",
            f"curated/tfda_devices/{orphan.name}",
            f"raw/tfda_devices/{first['raw_revision_id']}",
        ]
    )
    assert held["candidate_raw_revision_id"] in plan["keep_raw_revisions"]
    # Planning never removes anything.
    assert all((tmp_path / path).exists() for path in plan["remove_paths"])


def test_retention_plan_removes_nothing_with_three_or_fewer_versions(tmp_path, distribution):
    from taiwan_lab_mcp.tfda_autoupdate import plan_tfda_retention

    build_tfda_snapshot(_zip(ROWS), tmp_path)
    _auto(tmp_path, _version(2))
    assert plan_tfda_retention(tmp_path, keep_versions=3)["remove_paths"] == []


def test_cli_retention_plan_prints_without_removing(tmp_path, distribution, capsys):
    import taiwan_lab_mcp.data_cli as data_cli

    build_tfda_snapshot(_zip(ROWS), tmp_path)
    exit_code = data_cli.main(
        ["retention-plan", "tfda_devices", "--keep", "3", "--data-dir", str(tmp_path), "--json"]
    )
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["remove_paths"] == []
