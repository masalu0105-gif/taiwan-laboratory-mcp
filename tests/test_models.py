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
