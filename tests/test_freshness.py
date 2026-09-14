import json
from pathlib import Path


def test_sdd_fresh_01_internal_states_map_to_prd_freshness(tmp_path):
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.stores import read_source_status

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)

    available = read_source_status(tmp_path, "nhi_fee")
    assert available.availability == "available"
    assert available.serving_validation_status == "passed"
    assert available.serving_review_status == "approved"
    assert available.stale is False
    assert available.stale_reason_codes == []
    assert available.last_successful_check_at is not None
    assert available.content_age_status == "unknown"
    assert available.freshness_policy_version == "nhi-v1"

    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    check_path = tmp_path / Path(descriptor["latest_check_data_root_relative_path"])
    check = json.loads(check_path.read_text(encoding="utf-8"))
    check["stale"] = True
    check["stale_reason_codes"] = ["upstream_check_overdue"]
    check_bytes = canonical_json_bytes(check)
    check_path.write_bytes(check_bytes)
    descriptor["stale"] = True
    descriptor["stale_reason_codes"] = ["upstream_check_overdue"]
    descriptor["latest_check_sha256"] = sha256_bytes(check_bytes)
    descriptor_path.write_bytes(canonical_json_bytes(descriptor))

    stale = read_source_status(tmp_path, "nhi_fee")
    assert stale.availability == "available"
    assert stale.stale is True
    assert stale.stale_reason_codes == ["upstream_check_overdue"]
    assert stale.last_successful_check_at == available.last_successful_check_at
    assert stale.content_age_status == "unknown"

    unavailable = read_source_status(tmp_path / "missing", "nhi_fee")
    assert unavailable.availability == "data_unavailable"
    assert unavailable.stale is False
    assert unavailable.stale_reason_codes == []
    assert unavailable.content_age_status == "unknown"

    from taiwan_lab_mcp.acceptance import _node_registry

    assert (
        _node_registry()[
            (
                "SDD-FRESH-01",
                "tests/test_freshness.py::test_sdd_fresh_01_internal_states_map_to_prd_freshness",
            )
        ]
        == "executable"
    )


def _synthetic_nhi_root(tmp_path):
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    descriptor = json.loads(
        (tmp_path / "manifests" / "current" / "nhi_fee.json").read_text(encoding="utf-8")
    )
    return descriptor


def _utc(text):
    from datetime import datetime

    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def test_nhi_upstream_check_overdue_after_two_declared_daily_cycles(tmp_path):
    from datetime import timedelta

    from taiwan_lab_mcp.stores import read_nhi_state, read_source_status

    descriptor = _synthetic_nhi_root(tmp_path)
    last_success = _utc(descriptor["last_successful_check_at"])
    before = (tmp_path / "manifests" / "current" / "nhi_fee.json").read_bytes()

    at_limit = read_source_status(
        tmp_path, "nhi_fee", clock=lambda: last_success + timedelta(days=2)
    )
    assert at_limit.stale is False
    assert at_limit.stale_reason_codes == []

    def overdue_clock():
        return last_success + timedelta(days=2, seconds=1)

    overdue = read_source_status(tmp_path, "nhi_fee", clock=overdue_clock)
    assert overdue.availability == "available"
    assert overdue.stale is True
    assert overdue.stale_reason_codes == ["upstream_check_overdue"]
    assert overdue.last_successful_check_at == last_success

    state = read_nhi_state(tmp_path, clock=overdue_clock)
    assert state.availability == "available"
    assert state.status.stale is True
    assert state.status.stale_reason_codes == ["upstream_check_overdue"]
    assert state.provenance.stale is True
    assert state.provenance.stale_reason_codes == ["upstream_check_overdue"]

    # Owner decision 2026-09-14 (D-008): no hard-stop; keep serving with the warning.
    week_later = read_nhi_state(tmp_path, clock=lambda: last_success + timedelta(days=8))
    assert week_later.availability == "available"
    assert week_later.rows
    assert week_later.status.stale_reason_codes == ["upstream_check_overdue"]

    # The overdue flag is computed at read time; stored evidence is never rewritten.
    assert (tmp_path / "manifests" / "current" / "nhi_fee.json").read_bytes() == before


def test_nhi_overdue_merges_with_stored_reasons_in_registry_order(tmp_path):
    from datetime import timedelta

    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.stores import read_nhi_state, read_source_status

    descriptor = _synthetic_nhi_root(tmp_path)
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    check_path = tmp_path / Path(descriptor["latest_check_data_root_relative_path"])
    check = json.loads(check_path.read_text(encoding="utf-8"))
    for record in (check, descriptor):
        record["stale"] = True
        record["stale_reason_codes"] = ["upstream_verification_failed"]
    check_bytes = canonical_json_bytes(check)
    check_path.write_bytes(check_bytes)
    descriptor["latest_check_sha256"] = sha256_bytes(check_bytes)
    descriptor_path.write_bytes(canonical_json_bytes(descriptor))
    last_success = _utc(descriptor["last_successful_check_at"])

    def clock():
        return last_success + timedelta(days=3)

    status = read_source_status(tmp_path, "nhi_fee", clock=clock)
    assert status.stale_reason_codes == ["upstream_check_overdue", "upstream_verification_failed"]
    state = read_nhi_state(tmp_path, clock=clock)
    assert state.provenance.stale_reason_codes == [
        "upstream_check_overdue",
        "upstream_verification_failed",
    ]


def test_nhi_adapter_uses_context_clock_for_overdue_warning(tmp_path):
    from datetime import timedelta

    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.config import DataContext

    descriptor = _synthetic_nhi_root(tmp_path)
    last_success = _utc(descriptor["last_successful_check_at"])
    context = DataContext(
        mode="official_snapshot",
        data_root=tmp_path,
        clock=lambda: last_success + timedelta(days=5),
    )

    result = NHIAdapter(context).get_points("09006C")

    assert result.result_status == "ok"
    assert result.source_status.stale is True
    assert "upstream_check_overdue" in result.warnings
    assert result.provenance.stale_reason_codes == ["upstream_check_overdue"]


def test_nhi_overdue_rejects_naive_clock(tmp_path):
    from datetime import datetime

    import pytest

    from taiwan_lab_mcp.stores import read_source_status

    _synthetic_nhi_root(tmp_path)
    with pytest.raises(ValueError):
        read_source_status(tmp_path, "nhi_fee", clock=lambda: datetime(2030, 1, 1))


def test_sdd_fail_01_operational_integrity_is_data_unavailable(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    pointer_before = descriptor_path.read_bytes()
    descriptor = json.loads(pointer_before)
    check_path = tmp_path / Path(descriptor["latest_check_data_root_relative_path"])
    check = json.loads(check_path.read_text(encoding="utf-8"))
    check["latest_seen_artifact_sha256"] = "0" * 64
    check_path.write_bytes(canonical_json_bytes(check))

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "operational_status_integrity_failure"
    assert result.data_mode == "official_snapshot"
    assert result.sample_only is False
    assert result.items == []
    assert result.provenance is None
    assert descriptor_path.read_bytes() == pointer_before


_LIVE_OID = "2.16.886.101.20003.20065.20022"


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


def _metadata_response():
    body = json.dumps(
        {
            "success": True,
            "result": {
                "publisherOID": _LIVE_OID,
                "identifier": "A21030000I-D20021",
                "license": "1",
                "modifiedDate": "2026-09-15 07:05:47",
                "distribution": [
                    {
                        "resourceFormat": "CSV",
                        "resourceCharacterEncoding": "UTF-8",
                        "resourceDownloadUrl": "https://info.nhi.gov.tw/data.csv",
                    }
                ],
            },
        },
        ensure_ascii=False,
    ).encode()
    return _Response(200, body, {"Content-Type": "application/json"})


def _csv(rows):
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS

    return (chr(0xFEFF) + ",".join(NHI_COLUMNS) + "\n" + "\n".join(rows) + "\n").encode("utf-8")


def _csv_response(rows):
    return _Response(200, _csv(rows), {"Content-Type": "application/csv"})


_BASE_ROWS = ["09006C,200,20120101,29101231,HbA1c,醣化血紅素,"]


def _serve(data_root, rows):
    from taiwan_lab_mcp.importers.nhi import build_nhi_snapshot

    build_nhi_snapshot(_csv(rows), data_root)


def _run_check(data_root, *responses):
    from datetime import datetime, timezone

    from taiwan_lab_mcp.sync import run_nhi_upstream_check

    return run_nhi_upstream_check(
        data_root,
        expected_publisher_oid=_LIVE_OID,
        actor="unit-test-checker",
        opener=_Opener(*responses),
        clock=lambda: datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc),
    )


def _descriptor(data_root):
    return json.loads(
        (data_root / "manifests" / "current" / "nhi_fee.json").read_text(encoding="utf-8")
    )


def test_upstream_check_same_file_records_success_without_candidate(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter

    _serve(tmp_path, _BASE_ROWS)
    before = _descriptor(tmp_path)

    summary = _run_check(tmp_path, _metadata_response(), _csv_response(_BASE_ROWS))

    after = _descriptor(tmp_path)
    assert summary["result"] == "unchanged"
    assert summary["diff_data_root_relative_path"] is None
    assert after["generation"] == before["generation"] + 1
    assert after["serving_snapshot_id"] == before["serving_snapshot_id"]
    assert after["check_result"] == "success"
    assert after["latest_candidate_status"] == "none"
    assert after["stale"] is False
    assert after["last_check_at"] == "2026-09-15T01:00:00Z"
    assert after["last_successful_check_at"] == "2026-09-15T01:00:00Z"

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "ok"
    assert result.source_status.stale is False


def test_upstream_check_changed_file_keeps_serving_and_reports_diff(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter

    _serve(tmp_path, _BASE_ROWS)
    before = _descriptor(tmp_path)
    new_rows = [
        "09006C,210,20120101,29101231,HbA1c,醣化血紅素,",
        "09139C,200,20220301,29101231,,醣化白蛋白(GA),",
    ]

    summary = _run_check(tmp_path, _metadata_response(), _csv_response(new_rows))

    after = _descriptor(tmp_path)
    assert summary["result"] == "changed"
    assert after["serving_snapshot_id"] == before["serving_snapshot_id"]
    assert after["check_result"] == "success"
    assert after["latest_candidate_status"] == "review_pending"
    assert after["latest_candidate_id"] == summary["candidate_raw_revision_id"]
    assert after["stale"] is True
    assert after["stale_reason_codes"] == ["newer_candidate_pending_review"]

    diff = json.loads(
        (tmp_path / Path(summary["diff_data_root_relative_path"])).read_text(encoding="utf-8")
    )
    assert diff["added_codes"] == ["09139C"]
    assert diff["removed_codes"] == []
    assert diff["changed"] == [{"code": "09006C", "fields": ["健保支付點數"]}]
    assert diff["row_counts"] == {"serving": 1, "candidate": 2}
    assert diff["review_gate"]["row_count_change_exceeds_10_percent"] is True
    summary_text = (tmp_path / Path(summary["diff_summary_data_root_relative_path"])).read_text(
        encoding="utf-8"
    )
    assert "09139C" in summary_text
    assert "09006C" in summary_text

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "ok"
    assert result.items[0].record.points == 200
    assert result.source_status.latest_candidate_status == "review_pending"
    assert "newer_candidate_pending_review" in result.warnings


def test_upstream_check_fetch_failure_keeps_serving_and_marks_stale(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter

    _serve(tmp_path, _BASE_ROWS)
    before = _descriptor(tmp_path)

    summary = _run_check(
        tmp_path,
        _metadata_response(),
        _Response(503, b"upstream unavailable", {"Content-Type": "text/plain"}),
    )

    after = _descriptor(tmp_path)
    assert summary["result"] == "failed"
    assert summary["failed_stage"] == "fetch"
    assert after["serving_snapshot_id"] == before["serving_snapshot_id"]
    assert after["check_result"] == "failed"
    assert after["failed_stage"] == "fetch"
    assert after["latest_candidate_status"] == "none"
    assert after["stale_reason_codes"] == ["upstream_verification_failed"]
    assert after["last_successful_check_at"] == before["last_successful_check_at"]

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "ok"
    assert "upstream_verification_failed" in result.warnings


def test_upstream_check_without_serving_snapshot_only_writes_sync_report(tmp_path):
    summary = _run_check(tmp_path, _metadata_response(), _csv_response(_BASE_ROWS))

    assert summary["result"] == "no_serving_snapshot"
    assert not (tmp_path / "manifests").exists()
    assert (tmp_path / Path(summary["sync_report_data_root_relative_path"])).is_file()


def test_upstream_check_small_change_does_not_cross_ten_percent_gate(tmp_path):
    rows = [f"9{index:04d}C,{index},20240101,29101231,,項目{index}," for index in range(1, 21)]
    _serve(tmp_path, rows)

    summary = _run_check(
        tmp_path,
        _metadata_response(),
        _csv_response(rows + ["90021C,21,20240101,29101231,,項目21,"]),
    )

    assert summary["result"] == "changed"
    diff = json.loads(
        (tmp_path / Path(summary["diff_data_root_relative_path"])).read_text(encoding="utf-8")
    )
    assert diff["added_codes"] == ["90021C"]
    assert diff["review_gate"] == {
        "row_count_change_exceeds_10_percent": False,
        "unique_code_change_exceeds_10_percent": False,
    }


def test_cli_check_calls_upstream_check_with_explicit_oid_and_actor(tmp_path, monkeypatch, capsys):
    import taiwan_lab_mcp.data_cli as data_cli

    calls = []

    def fake_check(data_root, **kwargs):
        calls.append((data_root, kwargs))
        return {"result": "changed", "failed_stage": None, "error_code": None}

    monkeypatch.setattr("taiwan_lab_mcp.sync.run_nhi_upstream_check", fake_check)
    exit_code = data_cli.main(
        [
            "check",
            "nhi_fee",
            "--publisher-oid",
            _LIVE_OID,
            "--actor",
            "unit-test-checker",
            "--data-dir",
            str(tmp_path),
            "--json",
        ]
    )

    assert exit_code == 0
    assert calls == [
        (tmp_path, {"expected_publisher_oid": _LIVE_OID, "actor": "unit-test-checker"})
    ]
    assert json.loads(capsys.readouterr().out)["result"] == "changed"
