"""Serving the same read-only registry over a URL instead of a local subprocess."""

import asyncio
import json
from importlib.resources import files

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


def _contract_operations() -> set[str]:
    contract = json.loads(
        files("taiwan_lab_mcp").joinpath("contracts", "public-contract-v1.json").read_text("utf-8")
    )
    return {operation["name"] for operation in contract["operations"]}


def _list_tools_over_http() -> set[str]:
    from taiwan_lab_mcp.http_server import HttpSettings, build_http_app

    app = build_http_app(HttpSettings())

    async def run() -> set[str]:
        transport = httpx2.ASGITransport(app=app)
        # Talking to the app in-process skips the startup a real web server does, and the session
        # manager only starts there, so run the app's own startup and shutdown around the call.
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=transport, base_url="http://lab.test") as http:
                connection = streamable_http_client("http://lab.test/mcp", http_client=http)
                async with Client(connection) as client:
                    listed = await client.list_tools()
                    return {tool.name for tool in listed.tools}

    return asyncio.run(run())


def test_the_web_server_offers_the_same_operations_as_the_local_one() -> None:
    """A second way in must not become a second, quietly different tool set."""

    assert _list_tools_over_http() == _contract_operations()


def test_serving_only_to_this_computer_needs_no_extra_settings() -> None:
    from taiwan_lab_mcp.http_server import HttpSettings

    settings = HttpSettings()
    assert settings.host == "127.0.0.1"
    assert settings.path == "/mcp"
    settings.check()


def test_serving_beyond_this_computer_needs_the_public_name() -> None:
    """Without a Host allowlist anything that resolves to the machine can drive the server."""

    from taiwan_lab_mcp.http_server import HttpConfigurationError, HttpSettings

    settings = HttpSettings(host="0.0.0.0", mode="official_snapshot")
    with pytest.raises(HttpConfigurationError) as raised:
        settings.check()
    assert "TAIWAN_LAB_HTTP_ALLOWED_HOSTS" in str(raised.value)


def test_serving_beyond_this_computer_refuses_sample_data() -> None:
    """Synthetic fixtures are for trying the tools out, never for answering other people."""

    from taiwan_lab_mcp.http_server import HttpConfigurationError, HttpSettings

    settings = HttpSettings(host="0.0.0.0", allowed_hosts=("lab.example.com",), mode="sample")
    with pytest.raises(HttpConfigurationError) as raised:
        settings.check()
    assert "sample" in str(raised.value)


def test_a_public_run_is_allowed_once_both_are_set() -> None:
    from taiwan_lab_mcp.http_server import HttpSettings

    HttpSettings(
        host="0.0.0.0", allowed_hosts=("lab.example.com",), mode="official_snapshot"
    ).check()


def test_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from taiwan_lab_mcp.http_server import HttpSettings

    monkeypatch.setenv("TAIWAN_LAB_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("TAIWAN_LAB_HTTP_PORT", "9123")
    monkeypatch.setenv("TAIWAN_LAB_HTTP_PATH", "/lab")
    monkeypatch.setenv("TAIWAN_LAB_HTTP_ALLOWED_HOSTS", "lab.example.com, lab.example.org")
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")

    settings = HttpSettings.from_env()
    assert settings.host == "0.0.0.0"
    assert settings.port == 9123
    assert settings.path == "/lab"
    assert settings.allowed_hosts == ("lab.example.com", "lab.example.org")
    settings.check()


def test_a_port_that_is_not_a_number_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    from taiwan_lab_mcp.http_server import HttpConfigurationError, HttpSettings

    monkeypatch.setenv("TAIWAN_LAB_HTTP_PORT", "八千")
    with pytest.raises(HttpConfigurationError) as raised:
        HttpSettings.from_env()
    assert "TAIWAN_LAB_HTTP_PORT" in str(raised.value)


def test_a_question_asked_over_the_web_gets_the_same_answer_shape() -> None:
    """Listing the tools proves discovery works; this proves an answer travels back."""

    from taiwan_lab_mcp.http_server import HttpSettings, build_http_app

    app = build_http_app(HttpSettings())

    async def run() -> dict:
        transport = httpx2.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=transport, base_url="http://lab.test") as http:
                connection = streamable_http_client("http://lab.test/mcp", http_client=http)
                async with Client(connection) as client:
                    return (await client.call_tool("get_data_status", {})).model_dump(mode="json")

    result = asyncio.run(run())
    assert not result["is_error"]
    payload = json.loads(result["content"][0]["text"])
    assert payload["data_mode"] == "sample"
    assert {source["source_id"] for source in payload["sources"]} == {
        "cdc_manual",
        "cdc_recognized_labs",
        "nhi_fee",
        "tfda_device",
    }
