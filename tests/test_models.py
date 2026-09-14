import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from taiwan_lab_mcp.models import ToolResult


def test_sdd_obs_01_status_and_logs_exclude_query_content(tmp_path):
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS
    from taiwan_lab_mcp.stores import read_source_status
    from taiwan_lab_mcp.sync import run_nhi_sync

    secret_marker = "patient-secret-not-log"
    payload = (
        "\ufeff"
        + ",".join(NHI_COLUMNS)
        + "\n"
        + f"09006C,0,20120101,29101231,HbA1c,{secret_marker},\n"
    ).encode()
    report = run_nhi_sync(payload, tmp_path)
    serialized_report = json.dumps(report, ensure_ascii=False)
    assert secret_marker not in serialized_report
    assert "09006C" not in serialized_report
    assert str(tmp_path) not in serialized_report

    status = read_source_status(tmp_path, "nhi_fee")
    serialized_status = status.model_dump_json()
    assert "query" not in serialized_status
    assert secret_marker not in serialized_status
    assert str(tmp_path) not in serialized_status

    from taiwan_lab_mcp.acceptance import _node_registry

    assert (
        _node_registry()[
            (
                "SDD-OBS-01",
                "tests/test_models.py::test_sdd_obs_01_status_and_logs_exclude_query_content",
            )
        ]
        == "executable"
    )


def test_sdd_prov_01_every_item_and_child_has_typed_row_evidence(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))

    result = NHIAdapter().get_points("09006C")
    assert result.result_status == "ok"
    assert result.provenance is not None
    assert result.provenance.artifacts[0].artifact_id == "nhi-primary-csv"
    assert len(result.items) == 1

    item = result.items[0]
    evidence = item.evidence[0]
    assert evidence.artifact_id == "nhi-primary-csv"
    assert len(evidence.source_row_sha256) == 64
    assert evidence.locator.locator_type == "nhi_row"
    assert evidence.locator.source_row_number == 2
    assert evidence.raw_value_available is True
    assert ToolResult.model_validate(result.model_dump(mode="json")).result_status == "ok"


def test_tool_result_rejects_evidence_artifact_outside_provenance():
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter

    payload = NHIAdapter().get_points("SAMPLE001").model_dump(mode="python")
    payload["items"][0]["evidence"][0]["artifact_id"] = "unbound-artifact"

    with pytest.raises(ValidationError, match="evidence artifact must be declared in provenance"):
        ToolResult.model_validate(payload)


def test_tool_result_rejects_inconsistent_status_fields():
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter

    base = NHIAdapter().get_points("SAMPLE001").model_dump(mode="python")
    mutations = [
        ("result_status", "data_unavailable", "available result cannot be data_unavailable"),
        ("historical_truth_supported", False, "non-historical result must not claim history"),
        (
            "source_status.serving_review_status",
            "approved",
            "source status review must match provenance",
        ),
    ]
    for field, value, message in mutations:
        payload = deepcopy(base)
        target = payload
        if "." in field:
            parent, child = field.split(".", 1)
            target = payload[parent]
            target[child] = value
        else:
            target[field] = value
        with pytest.raises(ValidationError, match=message):
            ToolResult.model_validate(payload)


def test_tool_result_rejects_sample_provenance_snapshot_identity():
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter

    payload = NHIAdapter().get_points("SAMPLE001").model_dump(mode="python")
    payload["provenance"]["snapshot_id"] = "sample-must-not-have-id"

    with pytest.raises(ValidationError, match="sample provenance IDs must be null"):
        ToolResult.model_validate(payload)


def _model_transform() -> dict:
    return {
        "parser": {"version": "nhi-csv-v1", "bundle_sha256": "a" * 64},
        "schema": {"version": "nhi-7-v1", "bundle_sha256": "a" * 64},
        "normalization": {"version": "text-v1", "bundle_sha256": "a" * 64},
        "rules": [],
        "qualifier": {
            "name": None,
            "version": None,
            "spec_sha256": None,
            "extractor_output_sha256": None,
        },
    }


def _model_golden_case(**overrides) -> dict:
    case = {
        "golden_case_schema_version": 1,
        "case_id": "SYN-NHI-G-001",
        "source_id": "nhi_fee",
        "acceptance_id": "NHI-01",
        "source_title": "synthetic NHI golden fixture; not official evidence",
        "official_landing_url": "https://example.invalid/synthetic-nhi-fixture",
        "official_version_or_modified_at": None,
        "official_source": False,
        "artifact_id": "nhi-primary-csv",
        "raw_artifact_sha256": "b" * 64,
        "evidence_data_root_relative_path": None,
        "fixture_file": None,
        "fixture_sha256": None,
        "transform": _model_transform(),
        "input": {"code": "00101A"},
        "source_locator": {"locator_type": "nhi_row", "source_row_number": 2},
        "source_row_sha256": "c" * 64,
        "expected_status": "ok",
        "expected_fields": {"points": 0},
        "expected_warnings": ["coverage_review_incomplete"],
        "reviewer_id": None,
        "reviewer_role": None,
        "identity_assurance": None,
        "reviewed_at": None,
        "review_status": "review_pending",
    }
    case.update(overrides)
    return case


_REVIEWED = {
    "review_status": "approved",
    "reviewer_id": "unit-test-only-reviewer",
    "reviewer_role": "unit_test_role",
    "identity_assurance": "local_asserted",
}


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"unexpected": True}, "Extra inputs are not permitted"),
        ({"reviewer_id": "someone"}, "review_pending golden case must not carry reviewer evidence"),
        ({"review_status": "approved"}, "reviewed golden case requires reviewer evidence"),
        (
            {**_REVIEWED, "reviewed_at": "2026-09-14T00:00:00"},
            "reviewed_at must include a timezone",
        ),
        ({"official_source": True}, "official golden case requires a raw evidence path"),
        (
            {"official_source": True, "evidence_data_root_relative_path": "staged/nhi_fee/x.csv"},
            "official golden case requires a raw evidence path",
        ),
        (
            {"fixture_file": "tests/fixtures/synthetic/nhi.csv"},
            "fixture_file and fixture_sha256 must be set together",
        ),
        ({"transform": {"parser": {}}}, "transform must declare exactly"),
    ],
)
def test_golden_case_v1_is_strict_and_keeps_review_evidence_consistent(override, message):
    from taiwan_lab_mcp.models import GoldenCaseV1

    GoldenCaseV1.model_validate_json(json.dumps(_model_golden_case()))
    GoldenCaseV1.model_validate_json(
        json.dumps(_model_golden_case(**_REVIEWED, reviewed_at="2026-09-14T00:00:00+08:00"))
    )
    with pytest.raises(ValidationError, match=message):
        GoldenCaseV1.model_validate_json(json.dumps(_model_golden_case(**override)))


def test_qualification_candidate_case_registry_and_status_must_agree():
    from taiwan_lab_mcp.canonical import sha256_json
    from taiwan_lab_mcp.models import QualificationCandidateV1

    case = _model_golden_case()
    base = {
        "qualification_candidate_schema_version": 1,
        "source_id": "nhi_fee",
        "raw_revision_id": "nhi_fee-raw-x",
        "curated_build_id": "nhi_fee-build-x",
        "case_ids": ["SYN-NHI-G-001"],
        "case_count": 1,
        "cases": [
            {
                "golden_case": case,
                "golden_case_sha256": sha256_json(case),
                "evaluation_status": "passed",
                "failure_codes": [],
            }
        ],
        "input_artifact_hashes": [
            {"artifact_id": "nhi-primary-csv", "role": "primary", "sha256": "b" * 64}
        ],
        "curated_db_sha256": "d" * 64,
        "active_transform": _model_transform(),
        "automated_status": "passed",
        "synthetic_ci_status": "passed",
        "official_qualification_status": "not_qualified",
        "note": "offline synthetic fixture; not official qualification evidence",
    }
    QualificationCandidateV1.model_validate_json(json.dumps(base))

    failed_case = deepcopy(base)
    failed_case["cases"][0]["evaluation_status"] = "failed"
    failed_case["cases"][0]["failure_codes"] = ["FIELD_MISMATCH:points"]
    mutations = [
        ({"case_ids": ["OTHER"]}, "case_ids must match cases in order"),
        ({"case_count": 2}, "case_count must equal the number of cases"),
        (failed_case, "failed golden case requires automated_status=failed"),
        ({"official_qualification_status": "approved"}, "official_qualification_status"),
    ]
    for mutation, message in mutations:
        payload = mutation if "cases" in mutation else {**base, **mutation}
        with pytest.raises(ValidationError, match=message):
            QualificationCandidateV1.model_validate_json(json.dumps(payload))

    passed_with_codes = deepcopy(base)
    passed_with_codes["cases"][0]["failure_codes"] = ["FIELD_MISMATCH:points"]
    with pytest.raises(ValidationError, match="passed golden case must not carry failure codes"):
        QualificationCandidateV1.model_validate_json(json.dumps(passed_with_codes))


def test_qualification_certificate_cannot_list_cases_without_approval():
    from taiwan_lab_mcp.models import QualificationCertificateV1

    base = {
        "qualification_certificate_schema_version": 1,
        "source_id": "nhi_fee",
        "curated_build_id": "nhi_fee-build-x",
        "subject_digest": "a" * 64,
        "candidate_report_sha256": "b" * 64,
        "accepted_review_hashes": ["c" * 64],
        "approved_distinct_case_ids": [],
        "official_qualification_status": "not_qualified",
    }
    QualificationCertificateV1.model_validate_json(json.dumps(base))

    with pytest.raises(ValidationError, match="not_qualified certificate must not list"):
        QualificationCertificateV1.model_validate_json(
            json.dumps({**base, "approved_distinct_case_ids": ["NHI-G-001"]})
        )
    with pytest.raises(ValidationError, match="approved certificate requires at least 10"):
        QualificationCertificateV1.model_validate_json(
            json.dumps(
                {
                    **base,
                    "official_qualification_status": "approved",
                    "approved_distinct_case_ids": [f"NHI-G-{index:03d}" for index in range(1, 10)],
                }
            )
        )
