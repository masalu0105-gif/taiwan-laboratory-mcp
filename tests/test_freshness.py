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
