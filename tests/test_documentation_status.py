import json
import re
from importlib.resources import files
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _contract() -> dict:
    return json.loads(
        files("taiwan_lab_mcp")
        .joinpath("contracts", "public-contract-v1.json")
        .read_text(encoding="utf-8")
    )


def test_architecture_operation_count_tracks_public_contract():
    architecture = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    match = re.search(r"<!-- public-contract-operations: (\d+) -->", architecture)
    assert match, "architecture.md must declare its public contract operation count"
    assert int(match.group(1)) == len(_contract()["operations"])


def test_documented_official_sources_track_public_contract():
    data_sources = (REPO_ROOT / "docs" / "data-sources.md").read_text(encoding="utf-8")
    match = re.search(r"<!-- official-source-ids: ([a-z0-9_,]+) -->", data_sources)
    assert match, "data-sources.md must declare its official source IDs"
    documented = set(match.group(1).split(","))
    contracted = {
        operation["source"]
        for operation in _contract()["operations"]
        if operation.get("source")
        and operation["source"] != "all_sources"
        and not operation["source"].startswith("reserved_")
    }
    assert documented == contracted


def test_current_status_docs_do_not_repeat_retired_sample_only_claims():
    current_docs = "\n".join(
        (REPO_ROOT / relative).read_text(encoding="utf-8")
        for relative in ("docs/architecture.md", "docs/data-sources.md")
    )
    retired_claims = (
        "server.py` 註冊 18 個工具",
        "正式模式尚未實作",
        "尚未完成正式資料下載、匯入",
    )
    assert not [claim for claim in retired_claims if claim in current_docs]
