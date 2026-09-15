"""Owner 2026-09-15 extended automatic updates to NHI: checked new versions publish unattended."""

import json
from datetime import datetime, timezone

import pytest

import taiwan_lab_mcp.importers.nhi as nhi_importer
from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

OID = "2.16.886.101.20003.20065.20022"
CLOCK = datetime(2026, 9, 16, 1, 30, tzinfo=timezone.utc)
BASE = ["09006C,200,20120101,29101231,HbA1c,醣化血紅素,"] + [
    f"9{index:04d}Z,{index},20240101,29101231,,合成項目{index}," for index in range(1, 12)
]


def _csv(rows):
    return (chr(0xFEFF) + ",".join(NHI_COLUMNS) + "\n" + "\n".join(rows) + "\n").encode("utf-8")


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
            "identifier": "A21030000I-D20021",
            "license": "1",
            "modifiedDate": "2026-09-16 07:05:47",
            "distribution": [
                {
                    "resourceFormat": "CSV",
                    "resourceCharacterEncoding": "UTF-8",
                    "resourceDownloadUrl": "https://info.nhi.gov.tw/data.csv",
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


def _auto(data_root, rows):
    from taiwan_lab_mcp.nhi_autoupdate import run_nhi_auto_update

    return run_nhi_auto_update(
        data_root,
        expected_publisher_oid=OID,
        actor="unit-test-nhi-auto-update",
        opener=_Opener(
            _metadata(), _Response(200, _csv(rows), {"Content-Type": "application/csv"})
        ),
        clock=lambda: CLOCK,
    )


def _descriptor(data_root):
    return json.loads((data_root / "manifests" / "current" / "nhi_fee.json").read_bytes())


def _builds(data_root):
    return sorted(path.name for path in (data_root / "curated" / "nhi_fee").iterdir())


def _points(data_root, monkeypatch, code):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(data_root))
    return NHIAdapter().get_points(code).items[0].record


def test_same_version_needs_no_publish(tmp_path, distribution):
    build_nhi_snapshot(_csv(BASE), tmp_path)
    assert _auto(tmp_path, BASE)["result"] == "unchanged"
    assert len(_builds(tmp_path)) == 1


def test_checked_new_version_is_published_automatically(tmp_path, distribution, monkeypatch):
    build_nhi_snapshot(_csv(BASE), tmp_path)
    before = _descriptor(tmp_path)
    new_rows = ["09006C,210,20120101,29101231,HbA1c,醣化血紅素,"] + BASE[1:]

    summary = _auto(tmp_path, new_rows)

    assert summary["result"] == "published"
    assert summary["already_reported"] is False
    after = _descriptor(tmp_path)
    assert after["serving_snapshot_id"] == summary["published_snapshot_id"]
    assert after["serving_snapshot_id"] != before["serving_snapshot_id"]
    assert (after["stale"], after["latest_candidate_status"]) == (False, "none")
    build_dir = tmp_path / "curated" / "nhi_fee" / summary["published_snapshot_id"]
    review = json.loads((build_dir / "audit" / "reviews" / "PUB-R1-OWNER.json").read_bytes())
    assert review["reviewer_id"] == "automated-check:nhi-auto-update"
    assert review["reviewer_role"] == "automated_checker_delegated_by_owner"
    assert (review["protocol_id"], review["protocol_version"]) == ("nhi-r1-auto-review", "2")
    assert any(ref["artifact_id"] == "nhi-auto-roundtrip" for ref in review["evidence_refs"])
    certificate = json.loads((build_dir / "audit" / "golden-qualification.json").read_bytes())
    assert len(certificate["approved_distinct_case_ids"]) >= 10
    assert (tmp_path / summary["diff_summary_data_root_relative_path"]).is_file()
    assert _points(tmp_path, monkeypatch, "09006C").points == 210


def test_new_codes_without_a_scope_decision_count_as_lab_items(tmp_path, distribution, monkeypatch):
    # Owner 2026-09-15: a code nobody reviewed yet counts as a lab item until it is reviewed,
    # so one new code no longer marks every result as review_incomplete.
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter

    build_nhi_snapshot(_csv(BASE), tmp_path)
    new_rows = BASE[:-1] + ["99999Z,100,20260901,29101231,,新增合成項目,"]
    summary = _auto(tmp_path, new_rows)
    assert summary["result"] == "published"
    assert summary["new_codes_without_scope"] == ["99999Z"]

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("99999Z")
    record = result.items[0].record
    assert record.scope_status == "in_scope"
    assert "2026-09-15" in record.scope_basis_locator
    assert "先算檢驗" in record.scope_basis_locator
    assert result.coverage_status == "complete"
    assert "coverage_review_incomplete" not in result.warnings


def test_large_change_is_held_back_and_reported_once(tmp_path, distribution):
    build_nhi_snapshot(_csv(BASE), tmp_path)
    before = _descriptor(tmp_path)

    first = _auto(tmp_path, BASE[:10])
    assert first["result"] == "blocked"
    assert "row_count_change_exceeds_10_percent" in first["block_reasons"]
    assert first["already_reported"] is False
    assert _descriptor(tmp_path)["serving_snapshot_id"] == before["serving_snapshot_id"]

    second = _auto(tmp_path, BASE[:10])
    assert (second["result"], second["already_reported"]) == ("blocked", True)
    assert len(_builds(tmp_path)) == 1


def test_failed_full_table_check_keeps_the_old_version(tmp_path, distribution, monkeypatch):
    import taiwan_lab_mcp.nhi_autoupdate as autoupdate

    def broken(*args, **kwargs):
        raise autoupdate.AutoUpdateError("ROUNDTRIP_MISMATCH")

    monkeypatch.setattr(autoupdate, "verify_nhi_roundtrip", broken)
    build_nhi_snapshot(_csv(BASE), tmp_path)
    before = _descriptor(tmp_path)
    summary = _auto(tmp_path, ["09006C,210,20120101,29101231,HbA1c,醣化血紅素,"] + BASE[1:])
    assert (summary["result"], summary["error_code"]) == (
        "auto_publish_failed",
        "ROUNDTRIP_MISMATCH",
    )
    assert _descriptor(tmp_path)["serving_snapshot_id"] == before["serving_snapshot_id"]


def test_development_install_never_auto_publishes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("development", "d" * 64)
    )
    build_nhi_snapshot(_csv(BASE), tmp_path)
    before = _descriptor(tmp_path)
    summary = _auto(tmp_path, ["09006C,210,20120101,29101231,HbA1c,醣化血紅素,"] + BASE[1:])
    assert (summary["result"], summary["error_code"]) == (
        "auto_publish_failed",
        "APPLICATION_BUILD_IDENTITY_MISSING",
    )
    assert _descriptor(tmp_path)["serving_snapshot_id"] == before["serving_snapshot_id"]


def test_manual_owner_review_path_keeps_its_protocol(tmp_path):
    from taiwan_lab_mcp.importers.nhi import OWNER_REVIEW_PROTOCOL_ID, _owner_review_protocol

    assert _owner_review_protocol()[:2] == (OWNER_REVIEW_PROTOCOL_ID, "2")


def test_independent_roundtrip_agrees_with_the_official_build(tmp_path, distribution):
    from importlib.resources import files

    from taiwan_lab_mcp.nhi_autoupdate import verify_nhi_roundtrip
    from taiwan_lab_mcp.rules.nhi import ACTIVE_SCOPE_RULE_FILE

    build_nhi_snapshot(_csv(BASE), tmp_path)
    new_rows = ["09006C,210,20120101,29101231,HbA1c,醣化血紅素,"] + BASE[1:]
    published = _auto(tmp_path, new_rows)
    db_path = tmp_path / "curated" / "nhi_fee" / published["published_snapshot_id"] / "data.sqlite3"
    scope = files("taiwan_lab_mcp").joinpath("rules", "nhi_lab_scope", ACTIVE_SCOPE_RULE_FILE)
    report = verify_nhi_roundtrip(db_path, _csv(new_rows), scope.read_bytes())
    assert (report["result"], report["rows_compared"]) == ("passed", 12)


def test_cli_auto_publish_routes_nhi(tmp_path, monkeypatch, capsys):
    import taiwan_lab_mcp.data_cli as data_cli

    calls = []

    def fake(data_root, **kwargs):
        calls.append((data_root, kwargs))
        return {"result": "published", "failed_stage": None, "error_code": None}

    monkeypatch.setattr("taiwan_lab_mcp.nhi_autoupdate.run_nhi_auto_update", fake)
    arguments = ["--publisher-oid", OID, "--actor", "unit-test", "--data-dir", str(tmp_path)]
    assert data_cli.main(["check", "nhi_fee", *arguments, "--auto-publish", "--json"]) == 0
    assert calls == [(tmp_path, {"expected_publisher_oid": OID, "actor": "unit-test"})]
    assert json.loads(capsys.readouterr().out)["result"] == "published"
