import json
import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest
from pydantic import ValidationError


def test_public_contract_resource_declares_closed_24_tool_registry():
    contract = json.loads(
        files("taiwan_lab_mcp")
        .joinpath("contracts", "public-contract-v1.json")
        .read_text(encoding="utf-8")
    )
    assert contract["contract_version"] == "public-contract-v1"
    # 24 since the owner added one chapter 7 tool and one for chapters 3-6 (2026-09-16).
    assert len(contract["operations"]) == 24
    assert len({operation["name"] for operation in contract["operations"]}) == 24
    assert {operation["name"] for operation in contract["operations"]} == {
        "get_data_status",
        "search_disease",
        "get_specimen_requirement",
        "get_collection_method",
        "get_container",
        "get_transport_requirement",
        "get_submission_rule",
        "get_testing_location",
        "search_manual_procedure",
        "find_authorized_lab",
        "get_lab_scope",
        "search_payment_items",
        "search_lab_code",
        "get_points",
        "get_payment_rule",
        "search_reviewed_ivd",
        "search_ivd_candidates",
        "search_ivd",
        "get_license",
        "find_manufacturer",
        "list_matching_license_records",
        "compare_products",
        "standards_status",
        "eqa_status",
    }
    assert contract["safety_registry"]
    assert contract["source_payload_schemas"]
    assert contract["locator_schemas"]


def test_acceptance_report_blocks_planned_node_from_being_marked_passed(tmp_path):
    from taiwan_lab_mcp.acceptance import AcceptanceReportError, write_acceptance_report

    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(b"{}")
    digest = __import__("hashlib").sha256(evidence.read_bytes()).hexdigest()
    report = {
        "acceptance_report_schema_version": 1,
        "release_id": "p1.1-local",
        "requirement_id": "SDD-API-01",
        "node_id": "tests/test_mcp_stdio.py::test_sdd_api_01_public_contract_resource_matches_discovery",
        "node_status": "planned",
        "collected_node_count": 0,
        "exit_code": 0,
        "test_output_sha256": "a" * 64,
        "stdout_sha256": "b" * 64,
        "stderr_sha256": "c" * 64,
        "application_build_inventory_sha256": "d" * 64,
        "golden_qualification_sha256": "e" * 64,
        "source_review_evidence_sha256": "f" * 64,
        "evidence_refs": [{"path": "evidence.json", "sha256": digest}],
        "gate_disposition": "passed",
    }

    with pytest.raises(AcceptanceReportError, match="NODE_NOT_PASSABLE"):
        write_acceptance_report(tmp_path, report)


def test_acceptance_report_blocks_unregistered_node_from_being_marked_passed(tmp_path):
    from hashlib import sha256

    from taiwan_lab_mcp.acceptance import AcceptanceReportError, write_acceptance_report

    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(b"{}")
    digest = sha256(evidence.read_bytes()).hexdigest()
    report = {
        "acceptance_report_schema_version": 1,
        "release_id": "p1.1-local",
        "requirement_id": "SDD-API-01",
        "node_id": "tests/test_fake.py::test_unregistered_node",
        "node_status": "collected",
        "collected_node_count": 1,
        "exit_code": 0,
        "test_output_sha256": "a" * 64,
        "stdout_sha256": "b" * 64,
        "stderr_sha256": "c" * 64,
        "application_build_inventory_sha256": "d" * 64,
        "golden_qualification_sha256": "e" * 64,
        "source_review_evidence_sha256": "f" * 64,
        "evidence_refs": [{"path": "evidence.json", "sha256": digest}],
        "gate_disposition": "passed",
    }

    with pytest.raises(AcceptanceReportError, match="NODE_NOT_REGISTERED"):
        write_acceptance_report(tmp_path, report)


def test_acceptance_report_is_hash_bound_and_immutable(tmp_path):
    from hashlib import sha256

    from taiwan_lab_mcp.acceptance import AcceptanceReportError, write_acceptance_report
    from taiwan_lab_mcp.canonical import canonical_json_bytes

    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(b"verified evidence")
    digest = sha256(evidence.read_bytes()).hexdigest()
    report = {
        "acceptance_report_schema_version": 1,
        "release_id": "p1.1-local",
        "requirement_id": "SDD-API-01",
        "node_id": "tests/test_mcp_stdio.py::test_sdd_api_01_public_contract_resource_matches_discovery",
        "node_status": "collected",
        "collected_node_count": 1,
        "exit_code": 0,
        "test_output_sha256": "a" * 64,
        "stdout_sha256": "b" * 64,
        "stderr_sha256": "c" * 64,
        "application_build_inventory_sha256": "d" * 64,
        "golden_qualification_sha256": "e" * 64,
        "source_review_evidence_sha256": "f" * 64,
        "evidence_refs": [{"path": "evidence.json", "sha256": digest}],
        "gate_disposition": "passed",
    }

    report_path = write_acceptance_report(tmp_path, report)
    assert report_path.read_bytes() == canonical_json_bytes(report)
    assert write_acceptance_report(tmp_path, report) == report_path

    evidence.write_bytes(b"tampered evidence")
    with pytest.raises(AcceptanceReportError, match="EVIDENCE_HASH_MISMATCH"):
        write_acceptance_report(tmp_path, report)

    evidence.write_bytes(b"verified evidence")
    changed = dict(report)
    changed["gate_disposition"] = "not_closed"
    with pytest.raises(AcceptanceReportError, match="IMMUTABLE_REPORT_CONFLICT") as exc_info:
        write_acceptance_report(tmp_path, changed)
    assert str(tmp_path) not in str(exc_info.value)


def test_acceptance_report_rejects_non_string_status_without_leaking_type_error(tmp_path):
    from hashlib import sha256

    from taiwan_lab_mcp.acceptance import AcceptanceReportError, write_acceptance_report

    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(b"verified evidence")
    report = {
        "acceptance_report_schema_version": 1,
        "release_id": "p1.1-local",
        "requirement_id": "SDD-API-01",
        "node_id": "tests/test_mcp_stdio.py::test_sdd_api_01_public_contract_resource_matches_discovery",
        "node_status": {},
        "collected_node_count": 1,
        "exit_code": 0,
        "test_output_sha256": "a" * 64,
        "stdout_sha256": "b" * 64,
        "stderr_sha256": "c" * 64,
        "application_build_inventory_sha256": "d" * 64,
        "golden_qualification_sha256": "e" * 64,
        "source_review_evidence_sha256": "f" * 64,
        "evidence_refs": [
            {"path": "evidence.json", "sha256": sha256(b"verified evidence").hexdigest()}
        ],
        "gate_disposition": "passed",
    }

    with pytest.raises(AcceptanceReportError, match="REPORT_SCHEMA_INVALID"):
        write_acceptance_report(tmp_path, report)


def test_audit_validator_rejects_non_string_enum_without_leaking_type_error(tmp_path):
    from taiwan_lab_mcp.audit import AuditIntegrityError, _validate_review
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    manifest = json.loads(
        (tmp_path / "curated" / "nhi_fee" / built["snapshot_id"] / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    review_ref = manifest["audit_evidence"]["reviews"][0]
    review = json.loads(
        (tmp_path / Path(review_ref["data_root_relative_path"])).read_text(encoding="utf-8")
    )
    review["gate_id"] = {}

    with pytest.raises(AuditIntegrityError, match="review identity or decision invalid"):
        _validate_review(
            tmp_path,
            "nhi_fee",
            built["snapshot_id"],
            manifest["review_subject_digest"],
            review,
        )


def test_audit_validator_rejects_malformed_reference_without_leaking_type_error(tmp_path):
    from taiwan_lab_mcp.audit import AuditIntegrityError, validate_audit_evidence
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    manifest = json.loads(
        (tmp_path / "curated" / "nhi_fee" / built["snapshot_id"] / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    manifest["audit_evidence"]["validation"] = None

    with pytest.raises(AuditIntegrityError, match="validation reference schema invalid"):
        validate_audit_evidence(tmp_path, manifest)


def test_public_contract_contains_complete_request_response_payload_and_locator_schemas():
    from importlib.resources import files

    contract = json.loads(
        files("taiwan_lab_mcp")
        .joinpath("contracts", "public-contract-v1.json")
        .read_text(encoding="utf-8")
    )
    assert all("request_schema" in operation for operation in contract["operations"])
    assert all("schema" in schema for schema in contract["response_schemas"].values())
    assert all("schema" in schema for schema in contract["source_payload_schemas"].values())
    assert all("schema" in schema for schema in contract["locator_schemas"].values())


def test_nhi_importer_blocks_duplicate_current_code():
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, NHIImportError, parse_nhi_csv

    row = "09006C,200,20120101,29101231,HbA1c,醣化血紅素,"
    payload = ("\ufeff" + ",".join(NHI_COLUMNS) + "\n" + row + "\n" + row + "\n").encode()
    with pytest.raises(NHIImportError, match="DUPLICATE_LOGICAL_KEY"):
        parse_nhi_csv(payload)


def test_nhi_importer_blocks_duplicate_normalized_code():
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, NHIImportError, parse_nhi_csv

    rows = [
        "ＡＢＣ,0,20120101,29101231,HbA1c,醣化血素,",
        "abc,1,20120101,29101231,HbA1c,醣化血素,",
    ]
    payload = ("\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "\n".join(rows) + "\n").encode("utf-8")
    with pytest.raises(NHIImportError, match="DUPLICATE_LOGICAL_KEY"):
        parse_nhi_csv(payload)


def test_nhi_importer_blocks_utf8_replacement_character():
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, NHIImportError, parse_nhi_csv

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血素�,\n"
    ).encode("utf-8")
    with pytest.raises(NHIImportError, match="DECODE_REPLACEMENT_CHARACTER"):
        parse_nhi_csv(payload)


def test_nhi_importer_blocks_malformed_csv_quotes():
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, NHIImportError, parse_nhi_csv

    payload = (
        "\ufeff"
        + ",".join(NHI_COLUMNS)
        + "\n"
        + '09006C,0,20120101,29101231,HbA1c,醣化血素,"unterminated\n'
    ).encode("utf-8")
    with pytest.raises(NHIImportError, match="CSV_PARSE_ERROR"):
        parse_nhi_csv(payload)


def test_nhi_importer_maps_malformed_header_quotes_to_stable_error():
    from taiwan_lab_mcp.importers.nhi import NHIImportError, parse_nhi_csv

    with pytest.raises(NHIImportError, match="CSV_PARSE_ERROR"):
        parse_nhi_csv(b'"unterminated header\n')


def test_official_empty_data_root_is_unavailable_without_sample_fallback(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("SAMPLE001")
    assert result.result_status == "data_unavailable"
    assert result.data_mode == "official_snapshot"
    assert result.sample_only is False
    assert result.items == []
    assert result.provenance is None


def test_official_nhi_current_lookup_paginates_and_historical_query_fails_first(tmp_path):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff"
        + ",".join(NHI_COLUMNS)
        + "\n"
        + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,完整備註\n"
        + "09007C,12,20200101,29101231,Glucose,葡萄糖,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    try:
        adapter = NHIAdapter()
        current = adapter.get_points("09006C")
        assert current.result_status == "ok"
        assert current.items[0].record.code_raw == "09006C"
        assert current.items[0].record.points == 0
        assert current.items[0].record.matched_by == ["code"]
        assert current.coverage_status == "review_incomplete"
        assert current.items[0].evidence[0].source_row_sha256

        page = adapter.search_payment_items("0", limit=1, offset=0)
        assert page.returned_count == 1
        assert page.total_matches == 2
        assert page.truncated is True
        assert page.items[0].record.matched_by == ["code"]

        historical = adapter.get_points("09006C", "2026-09-13")
        assert historical.result_status == "historical_query_unsupported"
        assert historical.historical_truth_supported is False
        assert historical.items == []
        assert historical.provenance is not None
    finally:
        monkeypatch.undo()


def test_official_cdc_and_tfda_never_fallback_to_sample(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.cdc import CDCAdapter
    from taiwan_lab_mcp.adapters.tfda import TFDAAdapter

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    cdc_result = CDCAdapter().search_disease("麻疹")
    tfda_result = TFDAAdapter().search_ivd("HbA1c")
    for result in (cdc_result, tfda_result):
        assert result.result_status == "data_unavailable"
        assert result.data_mode == "official_snapshot"
        assert result.sample_only is False
        assert result.items == []
        assert result.provenance is None


def test_official_invalid_request_keeps_official_mode(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points(" ")
    assert result.result_status == "invalid_request"
    assert result.data_mode == "official_snapshot"
    assert result.sample_only is False
    assert result.provenance is None


def test_public_result_rejects_legacy_status_keys_and_keeps_count_non_serialized():
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter

    result = NHIAdapter().get_points("SAMPLE001")
    payload = result.model_dump(mode="json")
    assert "status" not in payload
    assert "count" not in payload
    assert result.status == result.result_status
    assert result.count == result.returned_count
    payload["status"] = "sample_only"
    with pytest.raises(ValidationError):
        type(result).model_validate(payload)


def test_nhi_rule_bundles_use_only_approved_entries_and_keep_alias_collisions():
    from taiwan_lab_mcp.rules.nhi import parse_alias_bundle, parse_scope_bundle

    scope = parse_scope_bundle(
        json.dumps(
            {
                "rule_version": "nhi-lab-scope-v1",
                "source_id": "nhi_fee",
                "status": "review_incomplete",
                "entries": [
                    {
                        "code": "09006C",
                        "scope_status": "in_scope",
                        "basis_type": "reviewed_source",
                        "basis_url": "https://example.test/scope",
                        "basis_locator": "case-NHI-001",
                        "rule_version": "nhi-lab-scope-v1",
                        "reviewer_id": "reviewer-1",
                        "reviewed_at": "2026-09-13T00:00:00Z",
                        "decision_status": "approved",
                    },
                    {
                        "code": "09007C",
                        "scope_status": "in_scope",
                        "basis_type": "reviewed_source",
                        "basis_url": "https://example.test/scope",
                        "basis_locator": "case-NHI-002",
                        "rule_version": "nhi-lab-scope-v1",
                        "reviewer_id": "reviewer-1",
                        "reviewed_at": "2026-09-13T00:00:00Z",
                        "decision_status": "review_pending",
                    },
                ],
            }
        ).encode()
    )
    assert scope["09006C"].basis_locator == "case-NHI-001"
    assert "09007C" not in scope

    aliases = parse_alias_bundle(
        json.dumps(
            {
                "rule_version": "nhi-aliases-v1",
                "source_id": "nhi_fee",
                "entries": [
                    {
                        "alias_raw": "糖化血色素",
                        "code": "09006C",
                        "language": "zh-Hant",
                        "basis_type": "reviewed_source",
                        "basis_url": "https://example.test/alias",
                        "basis_locator": "alias-1",
                        "rule_version": "nhi-aliases-v1",
                        "reviewer_id": "reviewer-1",
                        "reviewed_at": "2026-09-13T00:00:00Z",
                        "decision_status": "approved",
                        "collision_disposition": "return_all",
                    },
                    {
                        "alias_raw": "糖化血色素",
                        "code": "09007C",
                        "language": "zh-Hant",
                        "basis_type": "reviewed_source",
                        "basis_url": "https://example.test/alias",
                        "basis_locator": "alias-2",
                        "rule_version": "nhi-aliases-v1",
                        "reviewer_id": "reviewer-1",
                        "reviewed_at": "2026-09-13T00:00:00Z",
                        "decision_status": "approved",
                        "collision_disposition": "return_all",
                    },
                    {
                        "alias_raw": "不應命中",
                        "code": "09006C",
                        "language": "zh-Hant",
                        "basis_type": "unreviewed",
                        "basis_url": "https://example.test/alias",
                        "basis_locator": "alias-3",
                        "rule_version": "nhi-aliases-v1",
                        "reviewer_id": None,
                        "reviewed_at": None,
                        "decision_status": "review_pending",
                        "collision_disposition": "not_applicable",
                    },
                ],
            }
        ).encode()
    )
    assert aliases["糖化血色素"] == ("09006C", "09007C")
    assert "不應命中" not in aliases


def test_official_snapshot_is_read_only_and_stale_status_is_visible(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
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

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "ok"
    assert result.source_status.stale is True
    assert "upstream_check_overdue" in result.warnings
    assert result.provenance is not None
    assert result.provenance.snapshot_id == built["snapshot_id"]

    db_path = tmp_path / "curated" / "nhi_fee" / built["snapshot_id"] / "data.sqlite3"
    uri = f"file:{db_path.as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE must_not_write (value TEXT)")
    finally:
        connection.close()


def test_official_snapshot_tamper_is_integrity_failure_without_sample_fallback(
    tmp_path, monkeypatch
):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    db_path = tmp_path / "curated" / "nhi_fee" / built["snapshot_id"] / "data.sqlite3"
    db_path.write_bytes(db_path.read_bytes() + b"tampered")
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))

    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"
    assert result.data_mode == "official_snapshot"
    assert result.sample_only is False
    assert result.items == []
    assert result.provenance is None


def test_official_runtime_rejects_manifest_relocated_to_staged(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    current_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(current_path.read_text(encoding="utf-8"))
    source_manifest = tmp_path / Path(descriptor["manifest_data_root_relative_path"])
    staged_manifest = tmp_path / "staged" / "nhi_fee" / built["snapshot_id"] / "manifest.json"
    staged_manifest.parent.mkdir(parents=True)
    staged_manifest.write_bytes(source_manifest.read_bytes())
    descriptor["manifest_data_root_relative_path"] = str(
        staged_manifest.relative_to(tmp_path).as_posix()
    )
    descriptor["manifest_sha256"] = sha256_bytes(staged_manifest.read_bytes())
    current_path.write_bytes(canonical_json_bytes(descriptor))

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"
    assert result.items == []
    assert result.provenance is None


def test_official_runtime_rejects_curated_db_relocated_to_staged(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    current_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(current_path.read_text(encoding="utf-8"))
    manifest_path = tmp_path / Path(descriptor["manifest_data_root_relative_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_db = tmp_path / Path(manifest["publication"]["curated_build_relative_path"])
    staged_db = tmp_path / "staged" / "nhi_fee" / built["snapshot_id"] / "data.sqlite3"
    staged_db.parent.mkdir(parents=True)
    staged_db.write_bytes(source_db.read_bytes())
    manifest["publication"]["curated_build_relative_path"] = str(
        staged_db.relative_to(tmp_path).as_posix()
    )
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    descriptor["manifest_sha256"] = sha256_bytes(manifest_path.read_bytes())
    current_path.write_bytes(canonical_json_bytes(descriptor))

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"
    assert result.items == []
    assert result.provenance is None


def test_official_runtime_rejects_raw_artifact_relocated_to_staged(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    current_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(current_path.read_text(encoding="utf-8"))
    manifest_path = tmp_path / Path(descriptor["manifest_data_root_relative_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_raw = tmp_path / Path(manifest["artifacts"][0]["data_root_relative_path"])
    staged_raw = tmp_path / "staged" / "nhi_fee" / built["raw_revision_id"] / "source.csv"
    staged_raw.parent.mkdir(parents=True)
    staged_raw.write_bytes(source_raw.read_bytes())
    manifest["artifacts"][0]["data_root_relative_path"] = str(
        staged_raw.relative_to(tmp_path).as_posix()
    )
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    descriptor["manifest_sha256"] = sha256_bytes(manifest_path.read_bytes())
    current_path.write_bytes(canonical_json_bytes(descriptor))

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"
    assert result.items == []
    assert result.provenance is None


def test_official_runtime_rejects_audit_evidence_relocated_to_staged(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    current_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(current_path.read_text(encoding="utf-8"))
    manifest_path = tmp_path / Path(descriptor["manifest_data_root_relative_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review_ref = manifest["audit_evidence"]["reviews"][0]
    review_path = tmp_path / Path(review_ref["data_root_relative_path"])
    review = json.loads(review_path.read_text(encoding="utf-8"))
    source_evidence = review["evidence_refs"][0]
    source_path = tmp_path / Path(source_evidence["path"])
    staged_path = tmp_path / "staged" / "nhi_fee" / built["raw_revision_id"] / "evidence.csv"
    staged_path.parent.mkdir(parents=True)
    staged_path.write_bytes(source_path.read_bytes())
    source_evidence["path"] = str(staged_path.relative_to(tmp_path).as_posix())
    review_path.write_bytes(canonical_json_bytes(review))
    review_ref["sha256"] = sha256_bytes(review_path.read_bytes())
    manifest["audit_evidence"]["golden_qualification"] = manifest["audit_evidence"][
        "golden_qualification"
    ]
    golden_path = tmp_path / Path(
        manifest["audit_evidence"]["golden_qualification"]["data_root_relative_path"]
    )
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    golden["accepted_review_hashes"][0] = review_ref["sha256"]
    golden_path.write_bytes(canonical_json_bytes(golden))
    manifest["audit_evidence"]["golden_qualification"]["sha256"] = sha256_bytes(
        golden_path.read_bytes()
    )
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    descriptor["manifest_sha256"] = sha256_bytes(manifest_path.read_bytes())
    current_path.write_bytes(canonical_json_bytes(descriptor))

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"
    assert result.items == []
    assert result.provenance is None


def test_serving_old_snapshot_exposes_rejected_candidate_and_marks_stale(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.stores import read_source_status

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    check_path = tmp_path / Path(descriptor["latest_check_data_root_relative_path"])
    check = json.loads(check_path.read_text(encoding="utf-8"))
    candidate_id = "nhi-fee-candidate-rejected"
    reason = "newer_candidate_rejected"
    check.update(
        {
            "latest_candidate_id": candidate_id,
            "latest_candidate_status": "rejected",
            "stale": True,
            "stale_reason_codes": [reason],
        }
    )
    check_bytes = canonical_json_bytes(check)
    check_path.write_bytes(check_bytes)
    descriptor.update(
        {
            "latest_candidate_id": candidate_id,
            "latest_candidate_status": "rejected",
            "stale": True,
            "stale_reason_codes": [reason],
            "latest_check_sha256": sha256_bytes(check_bytes),
        }
    )
    descriptor_path.write_bytes(canonical_json_bytes(descriptor))

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "ok"
    assert result.source_status.latest_candidate_status == "rejected"
    assert result.source_status.stale is True
    assert reason in result.warnings
    assert result.provenance.stale is True
    status = read_source_status(tmp_path, "nhi_fee")
    assert status.latest_candidate_id == candidate_id
    assert status.latest_candidate_status == "rejected"


def test_nhi_builder_binds_serving_descriptor_to_immutable_check_record(tmp_path):
    from taiwan_lab_mcp.canonical import sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    check_relative = descriptor["latest_check_data_root_relative_path"]
    assert check_relative.startswith("checks/nhi_fee/")
    assert descriptor["latest_check_sha256"]
    check_path = tmp_path / Path(check_relative)
    assert check_path.is_file()
    check = json.loads(check_path.read_text(encoding="utf-8"))
    assert check["source_id"] == "nhi_fee"
    assert check["generation"] == descriptor["generation"]
    assert check["latest_candidate_status"] == descriptor["latest_candidate_status"]
    event_path = tmp_path / "publish-events" / "nhi_fee.jsonl"
    assert event_path.is_file()
    event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[0])
    assert event["result"] == "success"
    assert event["after_descriptor_sha256"] == sha256_bytes(descriptor_path.read_bytes())


def test_serving_descriptor_without_check_reference_fails_closed_operationally(
    tmp_path, monkeypatch
):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["latest_check_data_root_relative_path"] = None
    descriptor["latest_check_sha256"] = None
    descriptor_path.write_bytes(canonical_json_bytes(descriptor))

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "operational_status_integrity_failure"
    assert result.items == []
    assert result.provenance is None


def test_nhi_no_serving_descriptor_can_reveal_validated_candidate_status(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    for key in (
        "serving_snapshot_id",
        "serving_curated_build_id",
        "manifest_data_root_relative_path",
        "manifest_sha256",
        "parent_snapshot_id",
        "last_successful_publish_at",
        "publisher_actor_id",
        "latest_check_data_root_relative_path",
        "latest_check_sha256",
    ):
        descriptor[key] = None
    descriptor["latest_candidate_id"] = "nhi-fee-candidate-1"
    descriptor["latest_candidate_status"] = "review_pending"
    descriptor_path.write_bytes(canonical_json_bytes(descriptor))

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "no_serving_snapshot"
    assert result.source_status.latest_candidate_status == "review_pending"
    assert result.items == []
    assert result.provenance is None
    from taiwan_lab_mcp.stores import read_source_status

    status = read_source_status(tmp_path, "nhi_fee")
    assert status.latest_candidate_id == "nhi-fee-candidate-1"
    assert status.latest_candidate_status == "review_pending"


def test_missing_current_after_successful_publish_event_is_serving_integrity_failure(
    tmp_path, monkeypatch
):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    (tmp_path / "manifests" / "current" / "nhi_fee.json").unlink()
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))

    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"
    assert result.items == []
    assert result.provenance is None


def test_publish_generation_cas_rejects_stale_writer_without_mutating_current(tmp_path):
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import PublishError, publish_current_descriptor

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    before = descriptor_path.read_bytes()
    descriptor = json.loads(before)
    descriptor["generation"] = 1
    with pytest.raises(PublishError, match="PUBLISH_CAS_MISMATCH"):
        publish_current_descriptor(
            tmp_path,
            descriptor,
            expected_generation=0,
            expected_parent_snapshot_id=None,
            actor="offline-test-builder",
        )
    assert descriptor_path.read_bytes() == before


def test_publisher_rejects_missing_raw_artifact_before_pointer_replace(tmp_path):
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import PublishError, publish_current_descriptor

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    current_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    before_pointer = current_path.read_bytes()
    current = json.loads(before_pointer)
    manifest = json.loads(
        (tmp_path / Path(current["manifest_data_root_relative_path"])).read_text(encoding="utf-8")
    )
    raw_path = tmp_path / Path(manifest["artifacts"][0]["data_root_relative_path"])
    raw_path.unlink()

    check = json.loads(
        (tmp_path / Path(current["latest_check_data_root_relative_path"])).read_text(
            encoding="utf-8"
        )
    )
    check["check_id"] = "nhi_fee-check-publisher-raw"
    check["generation"] = 2
    check["checked_at"] = "2026-09-13T02:00:00Z"
    check_path = tmp_path / "checks" / "nhi_fee" / "nhi_fee-check-publisher-raw.json"
    check_path.write_bytes(canonical_json_bytes(check))

    descriptor = dict(current)
    descriptor.update(
        {
            "generation": 2,
            "parent_snapshot_id": built["snapshot_id"],
            "publisher_actor_id": "test-publisher",
            "last_successful_publish_at": "2026-09-13T02:00:00Z",
            "last_check_at": check["checked_at"],
            "last_successful_check_at": check["checked_at"],
            "latest_check_data_root_relative_path": "checks/nhi_fee/nhi_fee-check-publisher-raw.json",
            "latest_check_sha256": sha256_bytes(check_path.read_bytes()),
        }
    )

    with pytest.raises(PublishError, match="PUBLISH_DESCRIPTOR_INTEGRITY"):
        publish_current_descriptor(
            tmp_path,
            descriptor,
            expected_generation=1,
            expected_parent_snapshot_id=built["snapshot_id"],
            actor="test-publisher",
        )
    assert current_path.read_bytes() == before_pointer


def test_rollback_rejects_manifest_raw_path_drift_before_pointer_replace(tmp_path):
    import shutil

    from taiwan_lab_mcp.canonical import canonical_json_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import PublishError, rollback_current_descriptor

    def payload(code: str) -> bytes:
        return (
            "\ufeff"
            + ",".join(NHI_COLUMNS)
            + "\n"
            + f"{code},0,20120101,29101231,HbA1c,醣化血紅素,\n"
        ).encode()

    build_nhi_snapshot(payload("09006C"), tmp_path)
    second_root = tmp_path / "second-build"
    second = build_nhi_snapshot(payload("09007C"), second_root)
    for relative in (
        Path("raw") / "nhi_fee" / second["raw_revision_id"],
        Path("curated") / "nhi_fee" / second["snapshot_id"],
        Path("checks") / "nhi_fee" / f"nhi_fee-check-{second['snapshot_id'].split('-')[-1]}.json",
    ):
        source = second_root / relative
        target = tmp_path / relative
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    target_manifest_path = (
        tmp_path / "curated" / "nhi_fee" / second["snapshot_id"] / "manifest.json"
    )
    target_manifest = json.loads(target_manifest_path.read_text(encoding="utf-8"))
    target_manifest["artifacts"][0]["data_root_relative_path"] = (
        f"raw/nhi_fee/{second['raw_revision_id']}/artifacts/renamed-source.csv"
    )
    target_manifest_path.write_bytes(canonical_json_bytes(target_manifest))

    current_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    before_pointer = current_path.read_bytes()
    before_events = (tmp_path / "publish-events" / "nhi_fee.jsonl").read_bytes()
    with pytest.raises(PublishError, match="ROLLBACK_TARGET_INTEGRITY"):
        rollback_current_descriptor(
            tmp_path,
            "nhi_fee",
            second["snapshot_id"],
            expected_generation=1,
            reason="raw path drift",
            actor="test-operator",
        )
    assert current_path.read_bytes() == before_pointer
    assert (tmp_path / "publish-events" / "nhi_fee.jsonl").read_bytes() == before_events


def test_publisher_rejects_corrupt_current_descriptor_before_pointer_replace(tmp_path):
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import PublishError, publish_current_descriptor

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    current_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    current = json.loads(current_path.read_text(encoding="utf-8"))
    current["unexpected"] = True
    current_path.write_bytes(canonical_json_bytes(current))
    before_pointer = current_path.read_bytes()
    before_events = (tmp_path / "publish-events" / "nhi_fee.jsonl").read_bytes()

    check = json.loads(
        (tmp_path / Path(current["latest_check_data_root_relative_path"])).read_text(
            encoding="utf-8"
        )
    )
    check.update(
        {
            "check_id": "nhi_fee-check-corrupt-current",
            "generation": 2,
            "checked_at": "2026-09-13T03:00:00Z",
        }
    )
    check_path = tmp_path / "checks" / "nhi_fee" / "nhi_fee-check-corrupt-current.json"
    check_path.write_bytes(canonical_json_bytes(check))
    candidate = {key: value for key, value in current.items() if key != "unexpected"}
    candidate.update(
        {
            "generation": 2,
            "parent_snapshot_id": built["snapshot_id"],
            "last_successful_publish_at": "2026-09-13T03:00:00Z",
            "last_check_at": check["checked_at"],
            "last_successful_check_at": check["checked_at"],
            "latest_check_data_root_relative_path": (
                "checks/nhi_fee/nhi_fee-check-corrupt-current.json"
            ),
            "latest_check_sha256": sha256_bytes(check_path.read_bytes()),
        }
    )

    with pytest.raises(PublishError, match="CURRENT_POINTER_INTEGRITY"):
        publish_current_descriptor(
            tmp_path,
            candidate,
            expected_generation=1,
            expected_parent_snapshot_id=built["snapshot_id"],
            actor="offline-test-builder",
        )
    assert current_path.read_bytes() == before_pointer
    assert (tmp_path / "publish-events" / "nhi_fee.jsonl").read_bytes() == before_events


def test_rollback_switches_to_valid_target_with_new_generation_and_event(tmp_path, monkeypatch):
    import shutil

    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import rollback_current_descriptor

    def payload(code: str) -> bytes:
        return (
            "\ufeff"
            + ",".join(NHI_COLUMNS)
            + "\n"
            + f"{code},0,20120101,29101231,HbA1c,醣化血紅素,\n"
        ).encode()

    first = build_nhi_snapshot(payload("09006C"), tmp_path)
    second_root = tmp_path / "second-build"
    second = build_nhi_snapshot(payload("09007C"), second_root)
    for relative in (
        Path("raw") / "nhi_fee" / second["raw_revision_id"],
        Path("curated") / "nhi_fee" / second["snapshot_id"],
        Path("checks") / "nhi_fee" / f"nhi_fee-check-{second['snapshot_id'].split('-')[-1]}.json",
    ):
        source = second_root / relative
        target = tmp_path / relative
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    event = rollback_current_descriptor(
        tmp_path,
        "nhi_fee",
        second["snapshot_id"],
        expected_generation=1,
        reason="test rollback",
        actor="test-operator",
    )
    assert event["rollback"] is True
    assert event["target_curated_build_id"] == second["snapshot_id"]
    descriptor = json.loads(
        (tmp_path / "manifests" / "current" / "nhi_fee.json").read_text(encoding="utf-8")
    )
    assert descriptor["generation"] == 2
    assert descriptor["serving_snapshot_id"] == second["snapshot_id"]
    assert descriptor["parent_snapshot_id"] == first["snapshot_id"]

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    assert NHIAdapter().get_points("09007C").result_status == "ok"
    assert NHIAdapter().get_points("09006C").result_status == "not_found"


def test_rollback_cas_mismatch_preserves_current(tmp_path):
    import shutil

    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import PublishError, rollback_current_descriptor

    def payload(code: str) -> bytes:
        return (
            "\ufeff"
            + ",".join(NHI_COLUMNS)
            + "\n"
            + f"{code},0,20120101,29101231,HbA1c,醣化血紅素,\n"
        ).encode()

    build_nhi_snapshot(payload("09006C"), tmp_path)
    second_root = tmp_path / "second-build"
    second = build_nhi_snapshot(payload("09007C"), second_root)
    for relative in (
        Path("raw") / "nhi_fee" / second["raw_revision_id"],
        Path("curated") / "nhi_fee" / second["snapshot_id"],
        Path("checks") / "nhi_fee" / f"nhi_fee-check-{second['snapshot_id'].split('-')[-1]}.json",
    ):
        source = second_root / relative
        target = tmp_path / relative
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    current_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    before = current_path.read_bytes()
    with pytest.raises(PublishError, match="PUBLISH_CAS_MISMATCH"):
        rollback_current_descriptor(
            tmp_path,
            "nhi_fee",
            second["snapshot_id"],
            expected_generation=2,
            reason="stale writer",
            actor="test-operator",
        )
    assert current_path.read_bytes() == before


def test_recover_current_reconstructs_only_from_named_success_event(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import recover_current

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    event_path = tmp_path / "publish-events" / "nhi_fee.jsonl"
    event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[0])
    (tmp_path / "manifests" / "current" / "nhi_fee.json").unlink()

    recovered = recover_current(tmp_path, "nhi_fee", event["event_id"], actor="recovery-operator")
    assert recovered["event_type"] == "recover_current"
    assert recovered["recovered_from_event_id"] == event["event_id"]
    assert (tmp_path / "manifests" / "current" / "nhi_fee.json").is_file()

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    assert NHIAdapter().get_points("09006C").result_status == "ok"


def test_recover_current_ignores_residual_atomic_temp_file(tmp_path):
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import recover_current

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    event_path = tmp_path / "publish-events" / "nhi_fee.jsonl"
    event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[0])
    from taiwan_lab_mcp.canonical import canonical_json_bytes

    expected_descriptor = canonical_json_bytes(event["after_descriptor"])
    current_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    current_path.unlink()
    residual_temp = current_path.with_name(f".{current_path.name}.crash-leftover")
    residual_temp.write_bytes(b"incomplete descriptor")

    recovered = recover_current(tmp_path, "nhi_fee", event["event_id"], actor="recovery-operator")

    assert recovered["event_type"] == "recover_current"
    assert current_path.read_bytes() == expected_descriptor
    assert residual_temp.read_bytes() == b"incomplete descriptor"


def test_data_cli_recover_current_has_stable_json_result(tmp_path, capsys):
    from taiwan_lab_mcp.data_cli import main
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    event_path = tmp_path / "publish-events" / "nhi_fee.jsonl"
    event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[0])
    (tmp_path / "manifests" / "current" / "nhi_fee.json").unlink()

    assert (
        main(
            [
                "recover-current",
                "nhi_fee",
                "--publish-event",
                event["event_id"],
                "--actor",
                "cli-recovery",
                "--data-dir",
                str(tmp_path),
                "--json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "operation": "recover-current",
        "status": "success",
        "event_id": output["event_id"],
        "generation": 1,
    }


def test_data_cli_rollback_failure_has_stable_integrity_exit(tmp_path, capsys):
    from taiwan_lab_mcp.data_cli import main
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)

    assert (
        main(
            [
                "rollback",
                "nhi_fee",
                "nhi_fee-build-" + "0" * 64,
                "--expected-generation",
                "1",
                "--reason",
                "missing target",
                "--actor",
                "cli-operator",
                "--data-dir",
                str(tmp_path),
                "--json",
            ]
        )
        == 6
    )
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "operation": "rollback",
        "status": "failed",
        "error_code": "ROLLBACK_TARGET_UNAVAILABLE",
    }


def test_data_cli_validate_nhi_is_offline_and_returns_stable_failure_code(tmp_path, capsys):
    from taiwan_lab_mcp.data_cli import main
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS

    valid_path = tmp_path / "nhi.csv"
    valid_path.write_bytes(
        (
            "\ufeff"
            + ",".join(NHI_COLUMNS)
            + "\n"
            + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
        ).encode()
    )
    assert main(["validate", "nhi_fee", "--input", str(valid_path), "--json"]) == 0
    valid_result = json.loads(capsys.readouterr().out)
    assert valid_result == {
        "source_id": "nhi_fee",
        "validation_status": "passed",
        "rows": 1,
        "warnings": [],
    }

    invalid_path = tmp_path / "invalid.csv"
    invalid_path.write_bytes(b"not,nhi,data\n")
    assert main(["validate", "nhi_fee", "--input", str(invalid_path), "--json"]) == 4
    invalid_output = capsys.readouterr().out
    invalid_result = json.loads(invalid_output)
    assert invalid_result["source_id"] == "nhi_fee"
    assert invalid_result["validation_status"] == "failed"
    assert invalid_result["error_code"] == "SCHEMA_HEADER_MISMATCH"
    assert "invalid.csv" not in invalid_output


def test_nhi_snapshot_writes_hash_bound_audit_bundle_and_subject_digest(tmp_path):
    from taiwan_lab_mcp.audit import compute_review_subject_digest
    from taiwan_lab_mcp.canonical import sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    build_dir = tmp_path / "curated" / "nhi_fee" / built["snapshot_id"]
    manifest_path = build_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evidence = manifest["audit_evidence"]

    assert set(evidence) == {
        "validation",
        "qualification_candidate",
        "golden_qualification",
        "reviews",
    }
    for key in ("validation", "qualification_candidate", "golden_qualification"):
        path = tmp_path / Path(evidence[key]["data_root_relative_path"])
        assert path.is_file()
        assert sha256_bytes(path.read_bytes()) == evidence[key]["sha256"]
    assert [item["gate_id"] for item in evidence["reviews"]] == manifest["review"][
        "completed_gates"
    ]

    validation = json.loads(
        (tmp_path / Path(evidence["validation"]["data_root_relative_path"])).read_text(
            encoding="utf-8"
        )
    )
    candidate = json.loads(
        (tmp_path / Path(evidence["qualification_candidate"]["data_root_relative_path"])).read_text(
            encoding="utf-8"
        )
    )
    golden = json.loads(
        (tmp_path / Path(evidence["golden_qualification"]["data_root_relative_path"])).read_text(
            encoding="utf-8"
        )
    )
    assert validation["automated_status"] == "passed"
    assert candidate["synthetic_ci_status"] == "passed"
    assert golden["official_qualification_status"] == "not_qualified"
    expected_subject = compute_review_subject_digest(
        manifest,
        curated_db_sha256=manifest["publication"]["curated_sha256"],
        validation_report_sha256=evidence["validation"]["sha256"],
        qualification_candidate_sha256=evidence["qualification_candidate"]["sha256"],
    )
    assert manifest["review_subject_digest"] == expected_subject
    assert golden["subject_digest"] == expected_subject
    assert all(
        json.loads((tmp_path / Path(item["data_root_relative_path"])).read_text(encoding="utf-8"))[
            "subject_digest"
        ]
        == expected_subject
        for item in evidence["reviews"]
    )


def test_approved_qualification_requires_owner_gate_and_ten_cases(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    manifest_path = tmp_path / "curated" / "nhi_fee" / built["snapshot_id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    golden_ref = manifest["audit_evidence"]["golden_qualification"]
    golden_path = tmp_path / Path(golden_ref["data_root_relative_path"])
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    golden["official_qualification_status"] = "approved"
    golden_path.write_bytes(canonical_json_bytes(golden))
    golden_ref["sha256"] = sha256_bytes(golden_path.read_bytes())
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["manifest_sha256"] = sha256_bytes(manifest_path.read_bytes())
    descriptor_path.write_bytes(canonical_json_bytes(descriptor))
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))

    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"
    assert result.items == []


def test_approved_qualification_rejects_fewer_than_ten_cases():
    from taiwan_lab_mcp.audit import AuditIntegrityError, _validate_approved_qualification

    with pytest.raises(AuditIntegrityError, match="approved qualification cases invalid"):
        _validate_approved_qualification(
            {
                "source_id": "nhi_fee",
                "review": {"completed_gates": ["PUB-R1-OWNER"]},
                "artifacts": [],
            },
            {"case_ids": [], "cases": []},
            {
                "official_qualification_status": "approved",
                "approved_distinct_case_ids": [],
            },
        )


def test_official_runtime_rejects_missing_required_nhi_review_gates(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    manifest_path = tmp_path / "curated" / "nhi_fee" / built["snapshot_id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["review"]["required_gates"] = []
    manifest["review"]["completed_gates"] = []
    golden_ref = manifest["audit_evidence"]["golden_qualification"]
    golden_path = tmp_path / Path(golden_ref["data_root_relative_path"])
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    golden["accepted_review_hashes"] = []
    golden_path.write_bytes(canonical_json_bytes(golden))
    golden_ref["sha256"] = sha256_bytes(golden_path.read_bytes())
    manifest["audit_evidence"]["reviews"] = []
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["manifest_sha256"] = sha256_bytes(manifest_path.read_bytes())
    descriptor_path.write_bytes(canonical_json_bytes(descriptor))
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))

    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"


def test_official_runtime_rejects_manifest_row_count_mismatch(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    manifest_path = tmp_path / "curated" / "nhi_fee" / built["snapshot_id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["input_rows"] = 2
    manifest["counts"]["curated_rows"] = 2
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["manifest_sha256"] = sha256_bytes(manifest_path.read_bytes())
    descriptor_path.write_bytes(canonical_json_bytes(descriptor))
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))

    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"


def test_official_runtime_rejects_manifest_blocking_validation_error(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    manifest_path = tmp_path / "curated" / "nhi_fee" / built["snapshot_id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["validation"]["blocking_errors"] = ["ROW_DROP"]
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["manifest_sha256"] = sha256_bytes(manifest_path.read_bytes())
    descriptor_path.write_bytes(canonical_json_bytes(descriptor))
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))

    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"


def test_nhi_builder_rejects_existing_partial_build_before_mutation(tmp_path):
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, NHIImportError, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    manifest_path = tmp_path / "curated" / "nhi_fee" / built["snapshot_id"] / "manifest.json"
    before_manifest = manifest_path.read_bytes()
    (manifest_path.parent / "data.sqlite3").unlink()

    with pytest.raises(NHIImportError, match="IMMUTABLE_BUILD_EXISTS"):
        build_nhi_snapshot(payload, tmp_path)
    assert manifest_path.read_bytes() == before_manifest


def test_audit_evidence_tamper_fails_closed_without_sample_fallback(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    manifest = json.loads(
        (tmp_path / "curated" / "nhi_fee" / built["snapshot_id"] / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    validation_path = tmp_path / Path(
        manifest["audit_evidence"]["validation"]["data_root_relative_path"]
    )
    validation_path.write_bytes(validation_path.read_bytes() + b"tampered")

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "data_unavailable"
    assert result.availability_reason_code == "serving_integrity_failure"
    assert result.data_mode == "official_snapshot"
    assert result.sample_only is False
    assert result.items == []


def test_publisher_rejects_tampered_audit_target_before_pointer_replace(tmp_path):
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import PublishError, publish_current_descriptor

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    current_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    before = current_path.read_bytes()
    descriptor = json.loads(before)
    validation_path = tmp_path / Path(
        json.loads(
            (
                tmp_path
                / "curated"
                / "nhi_fee"
                / descriptor["serving_snapshot_id"]
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )["audit_evidence"]["validation"]["data_root_relative_path"]
    )
    validation_path.write_bytes(validation_path.read_bytes() + b"tampered")

    check_path = tmp_path / Path(descriptor["latest_check_data_root_relative_path"])
    check = json.loads(check_path.read_text(encoding="utf-8"))
    check["generation"] = 2
    check_path.write_bytes(canonical_json_bytes(check))
    candidate = dict(descriptor)
    candidate.update(
        {
            "generation": 2,
            "parent_snapshot_id": descriptor["serving_snapshot_id"],
            "latest_check_sha256": sha256_bytes(check_path.read_bytes()),
        }
    )
    with pytest.raises(PublishError, match="PUBLISH_DESCRIPTOR_INTEGRITY"):
        publish_current_descriptor(
            tmp_path,
            candidate,
            expected_generation=1,
            expected_parent_snapshot_id=descriptor["serving_snapshot_id"],
            actor="offline-test-builder",
        )
    assert current_path.read_bytes() == before


def test_two_concurrent_rollbacks_have_one_winner_and_monotonic_generation(tmp_path):
    import shutil
    from concurrent.futures import ThreadPoolExecutor

    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import PublishError, rollback_current_descriptor

    def payload(code: str) -> bytes:
        return (
            "\ufeff"
            + ",".join(NHI_COLUMNS)
            + "\n"
            + f"{code},0,20120101,29101231,HbA1c,醣化血紅素,\n"
        ).encode()

    build_nhi_snapshot(payload("09006C"), tmp_path)
    second_root = tmp_path / "second-build"
    second = build_nhi_snapshot(payload("09007C"), second_root)
    for relative in (
        Path("raw") / "nhi_fee" / second["raw_revision_id"],
        Path("curated") / "nhi_fee" / second["snapshot_id"],
        Path("checks") / "nhi_fee" / f"nhi_fee-check-{second['snapshot_id'].split('-')[-1]}.json",
    ):
        source = second_root / relative
        target = tmp_path / relative
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def attempt(actor: str):
        try:
            return rollback_current_descriptor(
                tmp_path,
                "nhi_fee",
                second["snapshot_id"],
                expected_generation=1,
                reason="concurrent rollback test",
                actor=actor,
            )["result"]
        except PublishError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, ("operator-a", "operator-b")))

    assert outcomes.count("success") == 1
    assert (
        sum(
            outcome in {"PUBLISH_CAS_MISMATCH", "ROLLBACK_TARGET_IS_CURRENT"}
            for outcome in outcomes
        )
        == 1
    )
    descriptor = json.loads(
        (tmp_path / "manifests" / "current" / "nhi_fee.json").read_text(encoding="utf-8")
    )
    assert descriptor["generation"] == 2
    assert descriptor["serving_snapshot_id"] == second["snapshot_id"]


def test_nhi_sync_failure_writes_attempt_report_and_preserves_current(tmp_path, capsys):
    from taiwan_lab_mcp.data_cli import main
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    current_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    before = current_path.read_bytes()
    input_path = tmp_path / "input.csv"
    input_path.write_bytes(payload)

    assert (
        main(
            [
                "sync",
                "nhi_fee",
                "--input",
                str(input_path),
                "--data-dir",
                str(tmp_path),
                "--fail-stage",
                "validate",
                "--json",
            ]
        )
        == 4
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed"
    assert report["stage"] == "validate"
    assert report["error_code"] == "VALIDATION_INJECTED_FAILURE"
    assert report["candidate_curated_build_id"] is None
    report_path = tmp_path / Path(report["report_data_root_relative_path"])
    assert report_path.is_file()
    report_bytes = report_path.read_bytes()
    assert str(tmp_path) not in report_bytes.decode("utf-8")
    assert current_path.read_bytes() == before


def test_nhi_sync_success_is_candidate_only_and_does_not_publish(tmp_path, capsys):
    from taiwan_lab_mcp.data_cli import main
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    current_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    before = current_path.read_bytes()
    input_path = tmp_path / "input.csv"
    input_path.write_bytes(payload)

    assert (
        main(
            [
                "sync",
                "nhi_fee",
                "--input",
                str(input_path),
                "--data-dir",
                str(tmp_path),
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "passed"
    assert report["stage"] == "validate"
    assert report["candidate_status"] == "review_pending"
    assert report["candidate_curated_build_id"] is not None
    assert (tmp_path / Path(report["report_data_root_relative_path"])).is_file()
    assert current_path.read_bytes() == before


@pytest.mark.parametrize(
    ("fail_stage", "expected_exit"),
    [("discover", 3), ("fetch", 3), ("parse", 4), ("normalize", 4), ("validate", 4)],
)
def test_nhi_sync_failure_injection_has_stage_specific_stable_code(
    tmp_path, capsys, fail_stage, expected_exit
):
    from taiwan_lab_mcp.data_cli import main
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS

    input_path = tmp_path / "input.csv"
    input_path.write_bytes(
        (
            "\ufeff"
            + ",".join(NHI_COLUMNS)
            + "\n"
            + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
        ).encode()
    )
    assert (
        main(
            [
                "sync",
                "nhi_fee",
                "--input",
                str(input_path),
                "--data-dir",
                str(tmp_path),
                "--fail-stage",
                fail_stage,
                "--json",
            ]
        )
        == expected_exit
    )
    report = json.loads(capsys.readouterr().out)
    assert report["stage"] == fail_stage
    expected_error_codes = {
        "discover": "DISCOVERY_INJECTED_FAILURE",
        "fetch": "FETCH_INJECTED_FAILURE",
        "parse": "PARSE_INJECTED_FAILURE",
        "normalize": "NORMALIZATION_INJECTED_FAILURE",
        "validate": "VALIDATION_INJECTED_FAILURE",
    }
    assert report["error_code"] == expected_error_codes[fail_stage]
    assert report["status"] == "failed"
    assert (tmp_path / Path(report["report_data_root_relative_path"])).is_file()
    assert not (tmp_path / "manifests" / "current" / "nhi_fee.json").exists()


def test_nhi_sync_without_input_is_discovery_failure_not_sample_fallback(tmp_path, capsys):
    from taiwan_lab_mcp.data_cli import main

    assert (
        main(
            [
                "sync",
                "nhi_fee",
                "--data-dir",
                str(tmp_path),
                "--json",
            ]
        )
        == 3
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed"
    assert report["stage"] == "discover"
    assert report["error_code"] == "DISCOVERY_INPUT_REQUIRED"
    assert report["candidate_curated_build_id"] is None
    assert not (tmp_path / "manifests" / "current" / "nhi_fee.json").exists()


def test_operational_check_writer_updates_status_without_changing_serving_identity(
    tmp_path, monkeypatch
):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.canonical import sha256_json
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import publish_operational_check

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, tmp_path)
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    before = json.loads(descriptor_path.read_text(encoding="utf-8"))
    check_path = tmp_path / Path(before["latest_check_data_root_relative_path"])
    check = json.loads(check_path.read_text(encoding="utf-8"))
    check.update(
        {
            "check_id": "nhi_fee-check-r2-"
            + sha256_json({"candidate": "rejected", "build": built["snapshot_id"]})[:16],
            "checked_at": "2026-09-13T01:00:00Z",
            "latest_candidate_id": "nhi-fee-candidate-rejected",
            "latest_candidate_status": "rejected",
            "check_result": "failed",
            "failed_stage": "fetch",
            "error_code": "FETCH_UPSTREAM_UNAVAILABLE",
            "stale": True,
            "stale_reason_codes": ["upstream_verification_failed", "newer_candidate_rejected"],
        }
    )
    event = publish_operational_check(
        tmp_path,
        "nhi_fee",
        check,
        expected_generation=before["generation"],
        actor="check-operator",
    )

    after = json.loads(descriptor_path.read_text(encoding="utf-8"))
    assert event["event_type"] == "check"
    assert after["generation"] == before["generation"] + 1
    assert after["serving_snapshot_id"] == before["serving_snapshot_id"]
    assert after["serving_curated_build_id"] == before["serving_curated_build_id"]
    assert after["manifest_sha256"] == before["manifest_sha256"]
    assert after["latest_candidate_status"] == "rejected"
    assert after["stale"] is True
    assert (
        after["latest_check_data_root_relative_path"]
        != before["latest_check_data_root_relative_path"]
    )
    assert (tmp_path / Path(after["latest_check_data_root_relative_path"])).is_file()

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "ok"
    assert result.source_status.latest_candidate_status == "rejected"
    assert result.source_status.stale is True
    assert "upstream_verification_failed" in result.warnings


def test_operational_check_writer_rejects_non_string_status_without_type_error(tmp_path):
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import PublishError, publish_operational_check

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    check = json.loads(
        (tmp_path / Path(descriptor["latest_check_data_root_relative_path"])).read_text(
            encoding="utf-8"
        )
    )
    for field in ("check_result", "latest_candidate_status"):
        invalid_check = dict(check)
        invalid_check[field] = {}
        with pytest.raises(PublishError, match="CHECK_RESULT_INVALID|CHECK_CANDIDATE_INVALID"):
            publish_operational_check(
                tmp_path,
                "nhi_fee",
                invalid_check,
                expected_generation=descriptor["generation"],
                actor="check-operator",
            )


def test_operational_check_writer_rejects_stale_generation_without_mutation(tmp_path):
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import PublishError, publish_operational_check

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    before = json.loads(descriptor_path.read_text(encoding="utf-8"))
    check = json.loads(
        (tmp_path / Path(before["latest_check_data_root_relative_path"])).read_text(
            encoding="utf-8"
        )
    )
    check["check_id"] = "nhi_fee-check-r2-stale-writer"
    check["checked_at"] = "2026-09-13T01:01:00Z"
    event = publish_operational_check(
        tmp_path,
        "nhi_fee",
        check,
        expected_generation=1,
        actor="first-check-writer",
    )
    assert event["result"] == "success"
    after_first = descriptor_path.read_bytes()

    stale_check = dict(check)
    stale_check["check_id"] = "nhi_fee-check-r2-late-writer"
    stale_check["checked_at"] = "2026-09-13T01:02:00Z"
    with pytest.raises(PublishError, match="PUBLISH_CAS_MISMATCH"):
        publish_operational_check(
            tmp_path,
            "nhi_fee",
            stale_check,
            expected_generation=1,
            actor="late-check-writer",
        )
    assert descriptor_path.read_bytes() == after_first
    assert not (tmp_path / "checks" / "nhi_fee" / "nhi_fee-check-r2-late-writer.json").exists()


def test_publish_lock_timeout_is_fail_closed(tmp_path):
    import subprocess
    import sys
    import time

    from taiwan_lab_mcp.publish import PublishError, _source_lock

    ready = tmp_path / "lock.ready"
    release = tmp_path / "lock.release"
    child = """
import sys
import time
from pathlib import Path
from taiwan_lab_mcp.publish import _source_lock

root = Path(sys.argv[1])
ready = Path(sys.argv[2])
release = Path(sys.argv[3])
with _source_lock(root / "locks" / "nhi_fee.publish.lock"):
    ready.write_bytes(b"ready")
    while not release.exists():
        time.sleep(0.01)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", child, str(tmp_path), str(ready), str(release)],
        cwd=str(Path.cwd()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        with pytest.raises(PublishError, match="PUBLISH_LOCK_TIMEOUT"):
            with _source_lock(tmp_path / "locks" / "nhi_fee.publish.lock", timeout_seconds=0.0):
                pass
    finally:
        release.write_bytes(b"release")
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr or stdout


def test_operational_check_event_append_failure_rolls_back_all_mutations(tmp_path, monkeypatch):
    import taiwan_lab_mcp.publish as publish_module
    from taiwan_lab_mcp.canonical import sha256_json
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import PublishError, publish_operational_check

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    before_descriptor = descriptor_path.read_bytes()
    event_path = tmp_path / "publish-events" / "nhi_fee.jsonl"
    before_events = event_path.read_bytes()
    descriptor = json.loads(before_descriptor)
    check = json.loads(
        (tmp_path / Path(descriptor["latest_check_data_root_relative_path"])).read_text(
            encoding="utf-8"
        )
    )
    check["check_id"] = (
        "nhi_fee-check-r2-event-failure-" + sha256_json({"case": "append-failure"})[:12]
    )
    check["checked_at"] = "2026-09-13T01:03:00Z"
    new_check_path = tmp_path / "checks" / "nhi_fee" / f"{check['check_id']}.json"

    def fail_append(*args, **kwargs):
        raise OSError("injected event append failure")

    monkeypatch.setattr(publish_module, "_append_event", fail_append)
    with pytest.raises(PublishError, match="PUBLISH_EVENT_APPEND_FAILURE"):
        publish_operational_check(
            tmp_path,
            "nhi_fee",
            check,
            expected_generation=descriptor["generation"],
            actor="event-failure-test",
        )
    assert descriptor_path.read_bytes() == before_descriptor
    assert event_path.read_bytes() == before_events
    assert not new_check_path.exists()


def test_publish_pointer_readback_failure_rolls_back_pointer_and_events(tmp_path, monkeypatch):
    import shutil

    import taiwan_lab_mcp.publish as publish_module
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
    from taiwan_lab_mcp.publish import PublishError, publish_current_descriptor

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    first = build_nhi_snapshot(payload, tmp_path)
    second_root = tmp_path / "second-build"
    second = build_nhi_snapshot(payload.replace(b"09006C", b"09007C"), second_root)
    for relative in (
        Path("raw") / "nhi_fee" / second["raw_revision_id"],
        Path("curated") / "nhi_fee" / second["snapshot_id"],
        Path("checks") / "nhi_fee" / f"nhi_fee-check-{second['snapshot_id'].split('-')[-1]}.json",
    ):
        source = second_root / relative
        target = tmp_path / relative
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    descriptor_path = tmp_path / "manifests" / "current" / "nhi_fee.json"
    event_path = tmp_path / "publish-events" / "nhi_fee.jsonl"
    before_descriptor = descriptor_path.read_bytes()
    before_events = event_path.read_bytes()
    descriptor = json.loads(
        (second_root / "manifests" / "current" / "nhi_fee.json").read_text(encoding="utf-8")
    )
    descriptor["generation"] = 2
    descriptor["parent_snapshot_id"] = first["snapshot_id"]
    descriptor["last_successful_publish_at"] = "2026-09-13T01:04:00Z"
    check_path = tmp_path / Path(descriptor["latest_check_data_root_relative_path"])
    check = json.loads(check_path.read_text(encoding="utf-8"))
    check["generation"] = 2
    check_path.write_bytes(canonical_json_bytes(check))
    descriptor["latest_check_sha256"] = sha256_bytes(check_path.read_bytes())

    original_atomic_write = publish_module._atomic_write

    def corrupt_pointer(path, value):
        payload_bytes = original_atomic_write(path, value)
        if path == descriptor_path:
            path.write_bytes(payload_bytes + b"\n")
        return payload_bytes

    monkeypatch.setattr(publish_module, "_atomic_write", corrupt_pointer)
    with pytest.raises(PublishError, match="PUBLISH_READBACK_FAILURE"):
        publish_current_descriptor(
            tmp_path,
            descriptor,
            expected_generation=1,
            expected_parent_snapshot_id=json.loads(before_descriptor)["serving_snapshot_id"],
            actor="offline-test-builder",
        )
    assert descriptor_path.read_bytes() == before_descriptor
    assert event_path.read_bytes() == before_events
