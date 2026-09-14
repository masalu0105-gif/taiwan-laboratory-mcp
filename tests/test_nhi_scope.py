import json
from importlib.resources import files

import pytest

from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, NHIImportError, build_nhi_snapshot


def _payload(*rows: str) -> bytes:
    return ("\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "\n".join(rows) + "\n").encode("utf-8")


def _packaged_bundle() -> dict:
    return json.loads(
        files("taiwan_lab_mcp").joinpath("rules", "nhi_lab_scope", "v2.json").read_text("utf-8")
    )


def _manifest(tmp_path, built: dict) -> dict:
    path = tmp_path / "curated" / "nhi_fee" / built["snapshot_id"] / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_packaged_scope_bundle_is_versioned_and_names_the_ai_reviewer():
    from taiwan_lab_mcp.rules.nhi import ACTIVE_SCOPE_RULE_VERSION, load_scope_rules

    bundle = _packaged_bundle()
    assert ACTIVE_SCOPE_RULE_VERSION == "nhi-lab-scope-v2"
    assert bundle["rule_version"] == "nhi-lab-scope-v2"
    assert {entry["rule_version"] for entry in bundle["entries"]} == {"nhi-lab-scope-v2"}
    assert {entry["reviewer_id"] for entry in bundle["entries"]} == {"ai-reviewer:claude-opus-5"}
    assert "not reviewed by a person" in bundle["note"]

    rules = load_scope_rules()
    assert rules["09006C"].scope_status == "in_scope"
    assert rules["18001C"].scope_status == "out_of_scope"
    assert rules["24009C"].scope_status == "in_scope"
    assert rules["30001C"].scope_status == "out_of_scope"
    assert rules["64"].scope_status == "in_scope"
    assert "30011B" not in rules
    assert all(rule.basis_locator for rule in rules.values())


def test_scope_bundle_rejects_entries_from_another_rule_version():
    from taiwan_lab_mcp.rules.nhi import NhiRuleError, parse_scope_bundle

    entry = {
        "code": "09006C",
        "scope_status": "in_scope",
        "basis_type": "nhi_fee_schedule_section",
        "basis_url": "https://example.test/scope",
        "basis_locator": "section",
        "rule_version": "nhi-lab-scope-v1",
        "reviewer_id": "ai-reviewer:test",
        "reviewed_at": "2026-09-14T00:00:00+08:00",
        "decision_status": "approved",
    }
    payload = {
        "rule_version": "nhi-lab-scope-v2",
        "source_id": "nhi_fee",
        "status": "complete",
        "entries": [entry],
    }
    with pytest.raises(NhiRuleError, match="SCOPE_SCHEMA_INVALID"):
        parse_scope_bundle(json.dumps(payload).encode())


def test_build_where_every_row_has_an_approved_scope_rule_serves_complete_coverage(
    tmp_path, monkeypatch
):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter

    built = build_nhi_snapshot(
        _payload(
            "09006C,200,20120101,29101231,HbA1c,醣化血紅素,",
            "18001C,150,20120101,29101231,EKG,心電圖,",
        ),
        tmp_path,
    )
    manifest = _manifest(tmp_path, built)
    assert manifest["review"]["capability_reviews"] == [
        {"capability": "nhi_lab_scope", "gate_id": "NHI-R1-SCOPE", "status": "approved"}
    ]
    assert {rule["name"]: rule["version"] for rule in manifest["transform"]["rules"]}[
        "nhi_lab_scope"
    ] == "nhi-lab-scope-v2"

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    adapter = NHIAdapter()
    lab = adapter.get_points("09006C")
    assert lab.coverage_status == "complete"
    assert "coverage_review_incomplete" not in lab.warnings
    assert lab.provenance.rule_bundle_version == "nhi-lab-scope-v2"
    record = lab.items[0].record
    assert record.scope_status == "in_scope"
    assert record.scope_rule_version == "nhi-lab-scope-v2"
    assert "第四項 生化學檢查" in record.scope_basis_locator
    assert not any("AI" in note for note in lab.notes)
    assert adapter.get_points("18001C").items[0].record.scope_status == "out_of_scope"


def test_build_with_a_row_missing_a_scope_rule_stays_review_incomplete(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter

    built = build_nhi_snapshot(
        _payload(
            "09006C,200,20120101,29101231,HbA1c,醣化血紅素,",
            "00101A,0,20120101,29101231,,前導零零點合成項目,",
        ),
        tmp_path,
    )
    manifest = _manifest(tmp_path, built)
    assert manifest["review"]["capability_reviews"][0]["status"] == "pending"

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.coverage_status == "review_incomplete"
    assert "coverage_review_incomplete" in result.warnings
    assert result.items[0].record.scope_status == "in_scope"


def _golden_case(payload: bytes, code: str, expected_warnings: list[str]) -> dict:
    from taiwan_lab_mcp.canonical import sha256_bytes
    from taiwan_lab_mcp.importers.nhi import active_nhi_transform, parse_nhi_csv

    row = next(row for row in parse_nhi_csv(payload).rows if row.code_raw == code)
    return {
        "golden_case_schema_version": 1,
        "case_id": "SYN-NHI-SCOPE-001",
        "source_id": "nhi_fee",
        "acceptance_id": "NHI-01",
        "source_title": "synthetic NHI golden fixture; not official evidence",
        "official_landing_url": "https://example.invalid/synthetic-nhi-fixture",
        "official_version_or_modified_at": None,
        "official_source": False,
        "artifact_id": "nhi-primary-csv",
        "raw_artifact_sha256": sha256_bytes(payload),
        "evidence_data_root_relative_path": None,
        "fixture_file": None,
        "fixture_sha256": None,
        "transform": active_nhi_transform(),
        "input": {"code": code},
        "source_locator": {"locator_type": "nhi_row", "source_row_number": row.source_row_number},
        "source_row_sha256": row.source_row_sha256,
        "expected_status": "ok",
        "expected_fields": {"scope_status": "in_scope"},
        "expected_warnings": expected_warnings,
        "reviewer_id": None,
        "reviewer_role": None,
        "identity_assurance": None,
        "reviewed_at": None,
        "review_status": "review_pending",
    }


def test_golden_case_warnings_follow_the_build_scope_coverage(tmp_path):
    from taiwan_lab_mcp.importers.nhi import evaluate_nhi_golden_cases

    payload = _payload("09006C,200,20120101,29101231,HbA1c,醣化血紅素,")
    complete = evaluate_nhi_golden_cases(payload, [_golden_case(payload, "09006C", [])])
    assert complete[0]["failure_codes"] == []

    stale = evaluate_nhi_golden_cases(
        payload, [_golden_case(payload, "09006C", ["coverage_review_incomplete"])]
    )
    assert stale[0]["failure_codes"] == ["WARNINGS_MISMATCH"]
    with pytest.raises(NHIImportError, match="GOLDEN_CASE_FAILED"):
        build_nhi_snapshot(
            payload,
            tmp_path,
            golden_cases=[_golden_case(payload, "09006C", ["coverage_review_incomplete"])],
        )
