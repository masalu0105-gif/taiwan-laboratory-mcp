"""Real subprocess transport; also run against an installed wheel from outside the repo."""

import asyncio
import os
import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters


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
                ("find_authorized_lab", {"query": "麻疹", "city": "台北"}),
                ("get_lab_scope", {"query": "麻疹"}),
                ("search_ivd", {"query": "HbA1c"}),
                ("get_license", {"license_no": "SAMPLE-IVD-001"}),
                ("find_manufacturer", {"name": "Sample Manufacturer"}),
                ("compare_products", {"query": "HbA1c", "limit": 1}),
                ("search_lab_code", {"query": "糖化血色素"}),
                ("get_points", {"code": "SAMPLE001"}),
                ("get_payment_rule", {"query": "HbA1c"}),
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
                assert data["count"] == 1, name
                assert data["sample_only"] is True
                assert data["items"][0]["provenance"]["method"] == "synthetic"
            status = await client.call_tool("get_data_status", {})
            assert status.structured_content["official_data_loaded"] is False
            eqa = await client.call_tool("eqa_status", {})
            assert eqa.structured_content["catalog_access_enabled"] is False
            standards = await client.call_tool("standards_status", {})
            assert set(standards.structured_content) == {"loinc", "fhir", "snomed_ct"}
            missing = await client.call_tool("search_ivd", {"query": "SAMPLE-NO-MATCH-123"})
            assert missing.structured_content["status"] == "not_found"
            assert missing.structured_content["sample_only"] is True
            invalid = await client.call_tool("search_lab_code", {"query": " "})
            assert invalid.is_error

    asyncio.run(asyncio.wait_for(exercise(), timeout=60))
