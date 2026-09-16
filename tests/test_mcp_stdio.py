"""Real subprocess transport; also run against an installed wheel from outside the repo."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters


def test_sdd_api_01_public_contract_resource_matches_discovery():
    from taiwan_lab_mcp.contracts import load_public_contract, operation_spec, response_schema
    from taiwan_lab_mcp.server import mcp

    contract = load_public_contract()
    discovered = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    assert set(discovered) == {operation["name"] for operation in contract["operations"]}

    for operation in contract["operations"]:
        name = operation["name"]
        tool = discovered[name]
        spec = operation_spec(name)
        expected_properties = {}
        expected_required = []
        for parameter in spec["parameters"]:
            property_schema = {"type": parameter["type"]}
            if parameter["nullable"]:
                property_schema = {"anyOf": [{"type": parameter["type"]}, {"type": "null"}]}
            if "default" in parameter:
                property_schema["default"] = parameter["default"]
            expected_properties[parameter["name"]] = property_schema
            if parameter["required"]:
                expected_required.append(parameter["name"])
        expected_request_schema = {
            "properties": expected_properties,
            "type": "object",
        }
        if expected_required:
            expected_request_schema["required"] = expected_required

        actual_request_schema = {
            "properties": {
                key: {field: value for field, value in property_schema.items() if field != "title"}
                for key, property_schema in tool.input_schema["properties"].items()
            },
            "type": tool.input_schema["type"],
        }
        if "required" in tool.input_schema:
            actual_request_schema["required"] = tool.input_schema["required"]
        assert actual_request_schema == spec["request_schema"]
        assert actual_request_schema == expected_request_schema
        assert tool.output_schema == response_schema(operation["response_schema"])
        for safety_key in operation["safety"]:
            assert f"{safety_key}=true" in (tool.description or "")


@pytest.mark.parametrize("protocol_mode", ["auto", "legacy"])
def test_stdio_tool_discovery_and_calls(tmp_path, protocol_mode):
    async def exercise():
        params = StdioServerParameters(
            command=os.environ.get("TAIWAN_LAB_TEST_PYTHON", sys.executable),
            args=["-m", "taiwan_lab_mcp.server"],
            cwd=tmp_path,
            env={"TAIWAN_LAB_DATA_MODE": "sample", "PYTHONIOENCODING": "utf-8"},
        )
        async with Client(params, mode=protocol_mode, read_timeout_seconds=20) as client:
            listing = await client.list_tools()
            names = {tool.name for tool in listing.tools}
            calls = [
                ("search_disease", {"query": "measles"}),
                ("get_specimen_requirement", {"disease": "麻疹"}),
                ("get_collection_method", {"disease": "麻疹"}),
                ("get_container", {"disease": "麻疹"}),
                ("get_transport_requirement", {"disease": "麻疹"}),
                ("get_submission_rule", {"disease": "麻疹"}),
                ("get_testing_location", {"disease": "示範傳染病甲"}),
                ("find_authorized_lab", {"query": "麻疹", "city": "台北"}),
                ("get_lab_scope", {"query": "麻疹"}),
                ("search_ivd", {"query": "HbA1c"}),
                ("search_reviewed_ivd", {"query": "HbA1c"}),
                ("search_ivd_candidates", {"query": "HbA1c"}),
                ("get_license", {"license_no": "SAMPLE-IVD-001"}),
                ("find_manufacturer", {"name": "Sample Manufacturer"}),
                ("compare_products", {"query": "HbA1c", "limit": 1}),
                ("list_matching_license_records", {"query": "HbA1c", "limit": 1}),
                ("search_lab_code", {"query": "糖化血色素"}),
                ("search_payment_items", {"query": "糖化血色素"}),
                ("get_points", {"code": "SAMPLE001"}),
                ("get_payment_rule", {"query": "SAMPLE001"}),
            ]
            assert names == {name for name, _ in calls} | {
                "get_data_status",
                "standards_status",
                "eqa_status",
            }
            for name, arguments in calls:
                result = await client.call_tool(name, arguments)
                assert not result.is_error, name
                data = result.structured_content
                assert data["result_status"] == (
                    "deprecated_unsupported" if name == "compare_products" else "ok"
                ), name
                assert data["sample_only"] is True
                if name != "compare_products":
                    assert data["returned_count"] == 1, name
                    assert data["provenance"]["source_id"]
            status = await client.call_tool("get_data_status", {})
            assert status.structured_content["data_mode"] == "sample"
            assert len(status.structured_content["sources"]) == 4
            eqa = await client.call_tool("eqa_status", {})
            assert eqa.structured_content["configured"] is False
            standards = await client.call_tool("standards_status", {})
            assert standards.structured_content["configured"] is False
            assert standards.structured_content["capabilities"] == ["LOINC", "FHIR", "SNOMED"]
            missing = await client.call_tool("search_ivd", {"query": "SAMPLE-NO-MATCH-123"})
            assert missing.structured_content["result_status"] == "not_found"
            assert missing.structured_content["sample_only"] is True
            invalid = await client.call_tool("search_lab_code", {"query": " "})
            assert invalid.structured_content["result_status"] == "invalid_request"

    asyncio.run(asyncio.wait_for(exercise(), timeout=60))


def test_nhi_04_as_of_is_explicitly_unsupported_in_p1_1(tmp_path):
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    data_root = tmp_path / "data"
    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, data_root)
    client_cwd = tmp_path / "client"
    client_cwd.mkdir()

    async def exercise():
        params = StdioServerParameters(
            command=os.environ.get("TAIWAN_LAB_TEST_PYTHON", sys.executable),
            args=["-m", "taiwan_lab_mcp.server"],
            cwd=client_cwd,
            env={
                "TAIWAN_LAB_DATA_MODE": "official_snapshot",
                "TAIWAN_LAB_DATA_DIR": str(data_root),
                "PYTHONIOENCODING": "utf-8",
            },
        )
        async with Client(params, mode="auto", read_timeout_seconds=20) as client:
            result = await client.call_tool("get_points", {"code": "09006C"})
            data = result.structured_content
            assert data["result_status"] == "ok"
            assert data["data_mode"] == "official_snapshot"
            assert data["sample_only"] is False
            assert data["coverage_status"] == "complete"
            assert data["provenance"]["source_id"] == "nhi_fee"

            historical = await client.call_tool(
                "get_points", {"code": "09006C", "as_of": "2020-01-01"}
            )
            historical_data = historical.structured_content
            assert historical_data["result_status"] == "historical_query_unsupported"
            assert historical_data["historical_truth_supported"] is False
            assert historical_data["availability"] == "available"

            status = await client.call_tool("get_data_status", {})
            nhi_status = next(
                item
                for item in status.structured_content["sources"]
                if item["source_id"] == "nhi_fee"
            )
            assert nhi_status["availability"] == "available"
            assert nhi_status["coverage_status"] == "complete"

    asyncio.run(asyncio.wait_for(exercise(), timeout=60))


def test_sdd_iso_01_official_never_falls_back_to_sample(tmp_path):
    client_cwd = tmp_path / "client"
    client_cwd.mkdir()
    data_root = tmp_path / "empty-data"
    data_root.mkdir()

    async def exercise():
        params = StdioServerParameters(
            command=os.environ.get("TAIWAN_LAB_TEST_PYTHON", sys.executable),
            args=["-m", "taiwan_lab_mcp.server"],
            cwd=client_cwd,
            env={
                "TAIWAN_LAB_DATA_MODE": "official_snapshot",
                "TAIWAN_LAB_DATA_DIR": str(data_root),
                "PYTHONIOENCODING": "utf-8",
            },
        )
        async with Client(params, mode="auto", read_timeout_seconds=20) as client:
            result = await client.call_tool("get_points", {"code": "09006C"})
            data = result.structured_content
            assert data["result_status"] == "data_unavailable"
            assert data["data_mode"] == "official_snapshot"
            assert data["sample_only"] is False
            assert data["availability"] == "data_unavailable"
            assert data["provenance"] is None

    asyncio.run(asyncio.wait_for(exercise(), timeout=60))


def test_official_stdio_stale_snapshot_keeps_serving_identity(tmp_path):
    from taiwan_lab_mcp.canonical import canonical_json_bytes, sha256_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    data_root = tmp_path / "data"
    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    built = build_nhi_snapshot(payload, data_root)
    descriptor_path = data_root / "manifests" / "current" / "nhi_fee.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    check_path = data_root / Path(descriptor["latest_check_data_root_relative_path"])
    check = json.loads(check_path.read_text(encoding="utf-8"))
    check["stale"] = True
    check["stale_reason_codes"] = ["upstream_check_overdue"]
    check_bytes = canonical_json_bytes(check)
    check_path.write_bytes(check_bytes)
    descriptor["stale"] = True
    descriptor["stale_reason_codes"] = ["upstream_check_overdue"]
    descriptor["latest_check_sha256"] = sha256_bytes(check_bytes)
    descriptor_path.write_bytes(canonical_json_bytes(descriptor))
    client_cwd = tmp_path / "client"
    client_cwd.mkdir()

    async def exercise():
        params = StdioServerParameters(
            command=os.environ.get("TAIWAN_LAB_TEST_PYTHON", sys.executable),
            args=["-m", "taiwan_lab_mcp.server"],
            cwd=client_cwd,
            env={
                "TAIWAN_LAB_DATA_MODE": "official_snapshot",
                "TAIWAN_LAB_DATA_DIR": str(data_root),
                "PYTHONIOENCODING": "utf-8",
            },
        )
        async with Client(params, mode="auto", read_timeout_seconds=20) as client:
            result = await client.call_tool("get_points", {"code": "09006C"})
            data = result.structured_content
            assert data["result_status"] == "ok"
            assert data["source_status"]["stale"] is True
            assert "upstream_check_overdue" in data["warnings"]
            assert data["provenance"]["snapshot_id"] == built["snapshot_id"]

    asyncio.run(asyncio.wait_for(exercise(), timeout=60))
