"""Recall gaps from the 2026-09-22 to 2026-10-15 query replay.

A multi-word licence question that misses as a phrase is answered by the intersection of
its terms. Disease and analyte synonyms are search-time only. Argument names that models
actually send are accepted, and the usage log shows an empty or failed call.
"""

import asyncio
import csv
import io
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx2
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from taiwan_lab_mcp.adapters.cdc import CDCAdapter
from taiwan_lab_mcp.adapters.nhi import NHIAdapter
from taiwan_lab_mcp.adapters.tfda import (
    TERM_INTERSECTION_NOTE,
    TERM_INTERSECTION_WARNING,
    TFDAAdapter,
)
from taiwan_lab_mcp.config import DataContext
from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot
from taiwan_lab_mcp.importers.tfda import TFDA_COLUMNS, build_tfda_snapshot

LICENSES = (
    "衛部醫器輸字第025569號",
    "衛部醫器輸字第026537號",
    "衛部醫器輸字第028931號",
)
CHINESE_ONLY = "衛部醫器輸字第030001號"


def _row(**values):
    base = dict.fromkeys(TFDA_COLUMNS, "")
    base.update(
        {
            "有效日期": "2027/01/31",
            "發證日期": "2020/01/01",
            "許可證種類": "09",
            "醫療器材級數": "2",
            "申請商名稱": "合成申請商股份有限公司",
            "申請商統一編號": "00012345",
            "製造商名稱": "Synthetic Maker One",
            "製造廠廠址": "1 Test Road",
            "製造廠國別": "JP",
            "異動日期": "2026/09/10",
            "醫器主類別一": "B 血液學及病理學",
            "醫器次類別一": "B.9225 合成品項",
        }
    )
    base.update(values)
    return [base[name] for name in TFDA_COLUMNS]


def _zip_bytes(rows):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(list(TFDA_COLUMNS))
    writer.writerows(rows)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("68_2.csv", (chr(0xFEFF) + buffer.getvalue()).encode("utf-8"))
    return archive.getvalue()


def _arkray_rows():
    names = (
        "糖化血色素分析儀 HA-8380V",
        "糖化血色素分析儀 HA-8180",
        "糖化血色素檢驗試劑",
    )
    rows = [
        _row(
            許可證字號=license_no,
            中文品名=name,
            英文品名="Automated Analyzer HA-8380V",
            製造商名稱="ARKRAY Factory Co., Ltd.",
        )
        for license_no, name in zip(LICENSES, names)
    ]
    rows.extend(
        [
            _row(
                許可證字號="衛部醫器輸字第030000號",
                中文品名="血糖機",
                英文品名="Glucose Meter",
                製造商名稱="ARKRAY Factory Co., Ltd.",
            ),
            _row(
                許可證字號="衛部醫器輸字第030002號",
                中文品名="別廠糖化血色素",
                英文品名="Other HbA1c Kit",
                製造商名稱="Other Maker",
            ),
            _row(
                許可證字號=CHINESE_ONLY,
                中文品名="僅中文糖化血色素",
                英文品名="Plain Reagent",
                製造商名稱="Plain Co",
            ),
            _row(
                許可證字號="衛部醫器輸字第030003號",
                中文品名="咖啡機",
                英文品名="Coffee Machine",
                製造商名稱="Cafe Co",
                醫器主類別一="J 一般醫院及個人使用裝置",
                醫器次類別一="J.9999 合成非體外診斷",
            ),
        ]
    )
    return rows


@pytest.fixture
def arkray(tmp_path):
    build_tfda_snapshot(_zip_bytes(_arkray_rows()), tmp_path)
    when = datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)
    adapter = TFDAAdapter(DataContext(mode="official_snapshot", data_root=tmp_path))
    adapter.context = DataContext(mode="official_snapshot", data_root=tmp_path, clock=lambda: when)
    return adapter


def _licenses(result):
    return {item.record.license_no_raw for item in result.items}


def test_multi_term_ivd_query_intersects_and_keeps_citations(arkray):
    phrase = arkray.list_matching_license_records("糖化血色素", limit=5)
    assert TERM_INTERSECTION_WARNING not in phrase.warnings

    found = {}
    for method in (
        arkray.search_ivd,
        arkray.search_reviewed_ivd,
        arkray.search_ivd_candidates,
        lambda query: arkray.list_matching_license_records(query, limit=5),
    ):
        result = method("ARKRAY 糖化血色素")
        assert result.result_status == "ok"
        assert result.total_matches == 3
        assert _licenses(result) == set(LICENSES)
        assert TERM_INTERSECTION_WARNING in result.warnings
        assert TERM_INTERSECTION_NOTE in result.notes
        found[result.operation] = result

    no_space = arkray.search_reviewed_ivd("ARKRAY糖化血色素")
    assert _licenses(no_space) == set(LICENSES)
    assert TERM_INTERSECTION_WARNING in no_space.warnings

    hba1c = arkray.list_matching_license_records("ARKRAY HbA1c", limit=5)
    assert _licenses(hba1c) == set(LICENSES)
    assert TERM_INTERSECTION_WARNING in hba1c.warnings

    direct = next(item for item in phrase.items if item.record.license_no_raw == LICENSES[0])
    fallback = next(
        item
        for item in found["list_matching_license_records"].items
        if item.record.license_no_raw == LICENSES[0]
    )
    assert fallback.record.name_zh_raw == direct.record.name_zh_raw == "糖化血色素分析儀 HA-8380V"
    assert "ARKRAY" not in (fallback.record.name_zh_raw or "")
    assert set(fallback.record.matched_by) >= {"manufacturer", "name_zh"}
    assert fallback.evidence[0].model_dump() == direct.evidence[0].model_dump()
    assert fallback.evidence[0].artifact_id
    assert len(fallback.evidence[0].source_row_sha256) == 64
    assert (
        fallback.evidence[0].locator.source_row_number
        == direct.evidence[0].locator.source_row_number
    )
    assert found["search_ivd"].provenance.model_dump() == phrase.provenance.model_dump()

    page = arkray.list_matching_license_records("ARKRAY 糖化血色素", limit=2, offset=0)
    assert (page.total_matches, page.returned_count, page.truncated) == (3, 2, True)
    beyond = arkray.list_matching_license_records("ARKRAY 糖化血色素", limit=2, offset=4)
    assert beyond.result_status == "not_found"
    assert beyond.total_matches == 3
    assert TERM_INTERSECTION_WARNING in beyond.warnings


def test_nonsense_intersection_stays_empty_and_single_terms_are_not_fallback(arkray):
    coffee = arkray.search_ivd("ARKRAY 咖啡機")
    assert coffee.result_status == "not_found"
    assert coffee.total_matches == 0
    assert coffee.items == []
    assert TERM_INTERSECTION_WARNING not in coffee.warnings

    also = arkray.list_matching_license_records("ARKRAY 咖啡機")
    assert also.total_matches == 0
    assert TERM_INTERSECTION_WARNING not in also.warnings

    brand = arkray.list_matching_license_records("ARKRAY")
    assert brand.total_matches > 0
    assert TERM_INTERSECTION_WARNING not in brand.warnings

    analyte = arkray.search_ivd("HbA1c")
    assert CHINESE_ONLY in _licenses(analyte)
    assert TERM_INTERSECTION_WARNING not in analyte.warnings
    chinese = next(item for item in analyte.items if item.record.license_no_raw == CHINESE_ONLY)
    assert chinese.record.name_zh_raw == "僅中文糖化血色素"
    assert "name_zh" in chinese.record.matched_by


def test_nine_terms_are_not_split_but_eight_still_intersect(tmp_path):
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india"]
    rows = [
        _row(
            許可證字號="衛部醫器輸字第040001號",
            中文品名="alpha bravo charlie",
            英文品名="delta echo foxtrot",
            製造商名稱="golf hotel",
            效能="india",
        )
    ]
    build_tfda_snapshot(_zip_bytes(rows), tmp_path)
    when = datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)
    adapter = TFDAAdapter(DataContext(mode="official_snapshot", data_root=tmp_path))
    adapter.context = DataContext(mode="official_snapshot", data_root=tmp_path, clock=lambda: when)

    eight = adapter.list_matching_license_records(" ".join(words[:8]))
    assert eight.total_matches == 1
    assert TERM_INTERSECTION_WARNING in eight.warnings

    nine = adapter.list_matching_license_records(" ".join(words))
    assert nine.total_matches == 0
    assert TERM_INTERSECTION_WARNING not in nine.warnings


def test_disease_synonyms_cover_labs_and_sample_fixtures():
    from taiwan_lab_mcp.importers.cdc_labs import (
        CDC_LABS_ROW_COLUMNS,
        CDC_LABS_TABLE,
        SEARCH_COLUMNS,
    )
    from taiwan_lab_mcp.importers.cdc_ods import CDC_LABS_FIELD_NAMES
    from taiwan_lab_mcp.rules.synonyms import analyte_needles, resolve_disease_query
    from taiwan_lab_mcp.util import tfda_search_normalize

    assert resolve_disease_query("dengue") == "登革熱"
    assert resolve_disease_query("dengue fever") == "登革熱"
    assert resolve_disease_query("rubeola") == "麻疹"
    assert resolve_disease_query("tb") == "結核病"
    assert analyte_needles("糖化") == ("糖化",)
    assert "糖化血色素" in analyte_needles("HbA1c")
    assert "hba1c" in analyte_needles("糖化血色素")

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    column_sql = ", ".join(
        f"{column} INTEGER NOT NULL"
        if column == "expanded_row_number"
        else f"{column} TEXT NOT NULL"
        for column in CDC_LABS_ROW_COLUMNS
    )
    connection.execute(f"CREATE TABLE {CDC_LABS_TABLE} ({column_sql})")

    def add(number, **fields):
        values = dict.fromkeys(CDC_LABS_FIELD_NAMES, "")
        values.update(fields)
        row = {
            "source_row_sha256": f"{number:064x}",
            "expanded_row_number": number,
            "sheet_name": "sheet",
            **values,
        }
        for column, field in SEARCH_COLUMNS:
            row[column] = tfda_search_normalize(values[field])
        connection.execute(
            f"INSERT INTO {CDC_LABS_TABLE} ({', '.join(CDC_LABS_ROW_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in CDC_LABS_ROW_COLUMNS)})",
            [row[column] for column in CDC_LABS_ROW_COLUMNS],
        )

    add(
        1,
        city="高雄市",
        institution="高雄示範實驗室",
        disease_name="登革熱",
        certificate_no="D1",
    )
    add(
        2,
        city="台南市",
        institution="國立成功大學醫學院附設醫院",
        disease_name="傷寒",
        certificate_no="T1",
    )

    from taiwan_lab_mcp.cdc_labs_store import search_labs
    from taiwan_lab_mcp.cdc_manual_store import search_clause_rows, search_specimen_rows

    def diseases(query, city=None):
        _total, rows = search_labs(connection, query=query, city=city, limit=20, offset=0)
        return [row["disease_name"] for row in rows]

    assert diseases("dengue") == ["登革熱"]
    assert diseases("dengue fever") == ["登革熱"]
    assert diseases("高雄 dengue") == ["登革熱"]
    assert diseases("dengue 咖啡機") == []
    assert diseases("typhoid") == ["傷寒"]
    assert diseases("成大 傷寒") == ["傷寒"]

    manual = sqlite3.connect(":memory:")
    manual.row_factory = sqlite3.Row
    manual.execute(
        "CREATE TABLE cdc_specimen_requirement "
        "(disease_search TEXT, disease_display TEXT, row_number INTEGER)"
    )
    manual.execute(
        "INSERT INTO cdc_specimen_requirement VALUES ('登革熱', '登革熱', 1), ('麻疹', '麻疹', 2)"
    )
    assert search_specimen_rows(manual, query="dengue fever")[0]["disease_display"] == "登革熱"
    assert search_specimen_rows(manual, query="rubeola")[0]["disease_display"] == "麻疹"
    manual.execute(
        "CREATE TABLE cdc_manual_clause (clause_number TEXT, text_search TEXT, row_number INTEGER)"
    )
    manual.execute("INSERT INTO cdc_manual_clause VALUES ('3.5', '示範步驟', 1)")
    manual.execute("INSERT INTO cdc_manual_clause VALUES ('9.1', '登革熱送驗', 2)")
    assert [row["clause_number"] for row in search_clause_rows(manual, query="3.5")] == ["3.5"]
    assert [row["clause_number"] for row in search_clause_rows(manual, query="dengue")] == ["9.1"]

    sample = CDCAdapter()
    assert sample.search_disease("dengue").items[0].record.disease == "登革熱"
    assert sample.search_disease("dengue fever").items[0].record.disease == "登革熱"
    assert sample.search_disease("rubeola").items[0].record.disease == "麻疹"
    assert sample.find_authorized_lab("measles", "台北").total_matches == 1
    assert sample.find_authorized_lab("麻疹", "高雄").total_matches == 0
    dengue = sample.find_authorized_lab("dengue")
    assert dengue.total_matches == 1
    assert dengue.items[0].record.city == "高雄市"
    assert dengue.items[0].record.disease_name == "登革熱（示範）"
    assert sample.find_authorized_lab("dengue", "台北").total_matches == 0
    assert sample.find_authorized_lab("dengue fever", "高雄").total_matches == 1


def test_hba1c_finds_a_chinese_only_fee_without_rewriting_it(tmp_path):
    payload = (
        "\ufeff"
        + ",".join(NHI_COLUMNS)
        + "\n"
        + "09099C,10,20120101,29101231,,醣化血紅素,只有中文\n"
    ).encode("utf-8")
    build_nhi_snapshot(payload, tmp_path)
    adapter = NHIAdapter(DataContext(mode="official_snapshot", data_root=tmp_path))

    result = adapter.search_payment_items("HbA1c")
    assert result.result_status == "ok"
    assert result.total_matches == 1
    record = result.items[0].record
    assert record.code_raw == "09099C"
    assert record.name_zh_raw == "醣化血紅素"
    assert record.name_en_raw in (None, "")
    assert "name_zh" in record.matched_by
    assert result.items[0].evidence[0].source_row_sha256

    british = adapter.search_payment_items("glycated haemoglobin")
    assert british.total_matches == 1
    assert british.items[0].record.name_zh_raw == "醣化血紅素"
    assert adapter.search_payment_items("糖化").total_matches == 0

    sample = NHIAdapter().search_payment_items("glycated hemoglobin")
    assert sample.total_matches == 1
    assert sample.items[0].record.name_zh_raw.startswith("糖化血色素")


def _tool_payload(result):
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if isinstance(structured, dict) and structured:
        return structured
    return json.loads(result.content[0].text)


def test_published_schema_stays_exact_while_obvious_names_are_accepted():
    from taiwan_lab_mcp.arguments import coerce_tool_arguments
    from taiwan_lab_mcp.server import mcp

    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    schema = tools["search_disease"].input_schema
    assert schema["required"] == ["query"]
    assert "keyword" not in schema["properties"]
    assert "licenseNo" not in tools["get_license"].input_schema["properties"]

    assert coerce_tool_arguments("search_disease", '{"keyword": "dengue"}') == {"query": "dengue"}
    assert coerce_tool_arguments("find_authorized_lab", {"query": "麻疹", "city": "  "}) == {
        "query": "麻疹",
        "city": None,
    }

    async def exercise():
        dengue = await mcp.call_tool("search_disease", {"keyword": "dengue"})
        disease_alias = await mcp.call_tool("search_disease", {"disease": "dengue"})
        same = await mcp.call_tool("search_disease", {"query": "麻疹", "keyword": "麻疹"})
        license_row = await mcp.call_tool("get_license", {"licence_no": "SAMPLE-IVD-001"})
        camel = await mcp.call_tool("get_license", {"licenseNo": "SAMPLE-IVD-001"})
        specimen = await mcp.call_tool("get_specimen_requirement", {"query": "麻疹"})
        maker = await mcp.call_tool("find_manufacturer", {"query": "Sample Manufacturer"})
        points = await mcp.call_tool("get_points", {"query": "SAMPLE001"})
        blank_city = await mcp.call_tool("find_authorized_lab", {"query": "麻疹", "city": ""})
        paged = await mcp.call_tool("search_payment_items", {"query": "糖化血色素", "limit": "5"})
        scoped = await mcp.call_tool(
            "list_matching_license_records",
            {"query": "HbA1c", "limit": 1, "ivd_scope": " Included ", "prefer_ivd": "true"},
        )
        return (
            dengue,
            disease_alias,
            same,
            license_row,
            camel,
            specimen,
            maker,
            points,
            blank_city,
            paged,
            scoped,
        )

    (
        dengue,
        disease_alias,
        same,
        license_row,
        camel,
        specimen,
        maker,
        points,
        blank_city,
        paged,
        scoped,
    ) = asyncio.run(exercise())
    for result in (
        dengue,
        disease_alias,
        same,
        license_row,
        camel,
        specimen,
        maker,
        points,
        blank_city,
        paged,
    ):
        payload = _tool_payload(result)
        assert payload["result_status"] == "ok"
    assert _tool_payload(dengue)["items"][0]["record"]["disease"] == "登革熱"
    assert _tool_payload(specimen)["query"] == {"disease": "麻疹"}
    assert _tool_payload(blank_city)["returned_count"] == 1
    assert _tool_payload(scoped)["result_status"] == "ok"
    assert CDCAdapter().find_authorized_lab("麻疹", "").result_status == "invalid_request"
    assert (
        TFDAAdapter().list_matching_license_records("HbA1c", prefer_ivd="true").result_status
        == "invalid_request"
    )

    with pytest.raises(ToolError, match="缺少參數"):
        asyncio.run(mcp.call_tool("search_disease", {"color": "red"}))
    with pytest.raises(ToolError, match="內容不同"):
        asyncio.run(mcp.call_tool("search_disease", {"query": "麻疹", "keyword": "登革熱"}))


def test_usage_log_records_result_count_and_error(tmp_path):
    from taiwan_lab_mcp.http_server import HttpSettings, build_http_app, summarize_response

    sse = (
        'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":'
        '{"isError":false,"content":[{"type":"text","text":'
        '"{\\"result_status\\":\\"not_found\\",\\"total_matches\\":0}"}]}}\n\n'
    ).encode()
    noted = summarize_response(sse, http_status=200)
    assert noted == {"result_count": 0, "error": False, "result_status": "not_found"}
    failed = summarize_response(
        b'{"jsonrpc":"2.0","id":1,"error":{"code":-32600}}', http_status=200
    )
    assert failed["error"] is True and failed["result_count"] is None

    log = tmp_path / "usage.jsonl"
    app = build_http_app(HttpSettings(usage_log_path=log))

    async def run():
        transport = httpx2.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=transport, base_url="http://lab.test") as http:
                headers = {"x-forwarded-for": "203.0.113.20"}
                ok = await http.post(
                    "/mcp",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "search_payment_items",
                            "arguments": {"query": "糖化血色素"},
                        },
                    },
                )
                missing = await http.post(
                    "/mcp",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "search_lab_code",
                            "arguments": {"query": " "},
                        },
                    },
                )
                bad = await http.post(
                    "/mcp",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "search_disease", "arguments": {"color": "red"}},
                    },
                )
                return ok.status_code, missing.status_code, bad.status_code

    ok_status, missing_status, bad_status = asyncio.run(run())
    assert ok_status == missing_status == bad_status == 200
    entries = [json.loads(line) for line in log.read_text("utf-8").splitlines()]
    by_id = {entry["tool"] + str(index): entry for index, entry in enumerate(entries)}
    assert len(entries) == 3
    assert entries[0]["tool"] == "search_payment_items"
    assert entries[0]["result_count"] == 1
    assert entries[0]["error"] is False
    assert entries[0]["result_status"] == "ok"
    assert entries[0]["status"] == 200
    assert "ms" in entries[0]
    assert entries[1]["result_count"] == 0
    assert entries[1]["error"] is True
    assert entries[1]["result_status"] == "invalid_request"
    assert entries[2]["error"] is True
    assert entries[2]["result_count"] is None
    assert by_id

    limited = tmp_path / "limited.jsonl"
    limited_app = build_http_app(HttpSettings(rate_limit_per_minute=1, usage_log_path=limited))

    async def flood():
        transport = httpx2.ASGITransport(app=limited_app)
        async with limited_app.router.lifespan_context(limited_app):
            async with httpx2.AsyncClient(transport=transport, base_url="http://lab.test") as http:
                for _ in range(2):
                    await http.post(
                        "/mcp",
                        headers={"x-forwarded-for": "203.0.113.21"},
                        json={"jsonrpc": "2.0"},
                    )

    asyncio.run(flood())
    refused = [
        json.loads(line) for line in limited.read_text("utf-8").splitlines() if '"refused"' in line
    ]
    assert refused[-1]["error"] is True
    assert refused[-1]["result_count"] is None
    assert refused[-1]["refused"] == "rate_limit_exceeded"


def _usage_report_bash_available() -> bool:
    """Windows `bash` is the WSL stub and cannot run the usage-report script."""
    if sys.platform == "win32":
        return False
    try:
        completed = subprocess.run(
            ["bash", "-c", "printf ok"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and "ok" in completed.stdout


@pytest.mark.skipif(
    not _usage_report_bash_available(),
    reason="usage report needs a real bash; Windows bash is the WSL stub",
)
def test_usage_report_lists_empty_and_failed_calls(tmp_path):
    log = tmp_path / "usage.jsonl"
    rows = [
        {
            "at": "2026-10-01T01:00:00+00:00",
            "client": "203.0.113.30",
            "tool": "search_ivd",
            "arguments": '{"query":"舊查詢"}',
            "status": 200,
        },
        {
            "at": "2026-10-01T02:00:00+00:00",
            "client": "203.0.113.30",
            "tool": "search_ivd",
            "arguments": '{"query":"ARKRAY 咖啡機"}',
            "status": 200,
            "result_count": 0,
            "error": False,
            "result_status": "not_found",
        },
        {
            "at": "2026-10-01T03:00:00+00:00",
            "client": "203.0.113.30",
            "tool": "search_disease",
            "arguments": '{"color":"red"}',
            "status": 200,
            "result_count": None,
            "error": True,
            "result_status": None,
        },
    ]
    log.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    env = {**os.environ, "TAIWAN_LAB_PRODUCTION_BASE": str(tmp_path)}
    script = Path(__file__).resolve().parents[1] / "scripts/ops/grok-production-usage-report.sh"
    completed = subprocess.run(
        ["bash", str(script), "all"],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "查無資料 1 次" in completed.stdout
    assert "ARKRAY 咖啡機" in completed.stdout
    assert "錯誤 1 次" in completed.stdout
    assert "舊查詢" in completed.stdout
