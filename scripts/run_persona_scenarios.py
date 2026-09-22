#!/usr/bin/env python3
"""Run the reviewed 10-persona/100-question matrix through a real MCP endpoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

DATA_TOOLS = {
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
}


def _payload(result: Any) -> dict[str, Any]:
    if result.is_error:
        raise AssertionError("MCP operation returned is_error=true")
    if isinstance(result.structured_content, dict):
        return result.structured_content
    if not result.content:
        raise AssertionError("MCP operation returned no content")
    value = json.loads(result.content[0].text)
    if not isinstance(value, dict):
        raise AssertionError("MCP operation payload is not an object")
    return value


def _lookup(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(path)
    return current


def _validate_case(case: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = case["expect"]
    status = payload.get("result_status")
    statuses = expected.get("statuses", [expected.get("status", "ok")])
    if status not in statuses:
        errors.append(f"result_status={status!r}, expected one of {statuses!r}")

    if "min_returned" in expected and payload.get("returned_count", 0) < expected["min_returned"]:
        errors.append(
            f"returned_count={payload.get('returned_count')!r} < {expected['min_returned']}"
        )
    if "max_returned" in expected and payload.get("returned_count", 0) > expected["max_returned"]:
        errors.append(
            f"returned_count={payload.get('returned_count')!r} > {expected['max_returned']}"
        )
    for warning in expected.get("warnings", []):
        if warning not in payload.get("warnings", []):
            errors.append(f"missing warning {warning!r}")
    for path, value in expected.get("equals", {}).items():
        try:
            actual = _lookup(payload, path)
        except (KeyError, IndexError, ValueError, TypeError):
            errors.append(f"missing path {path!r}")
        else:
            if actual != value:
                errors.append(f"{path}={actual!r}, expected {value!r}")

    tool = case["tool"]
    if tool in DATA_TOOLS and status != "invalid_request":
        if payload.get("data_mode") != "official_snapshot":
            errors.append(f"unsafe data_mode={payload.get('data_mode')!r}")
        if payload.get("sample_only") is not False:
            errors.append(f"unsafe sample_only={payload.get('sample_only')!r}")
        if payload.get("availability") != "available":
            errors.append(f"availability={payload.get('availability')!r}")
        if payload.get("snapshot_traceable") is not True:
            errors.append("snapshot_traceable is not true")
        provenance = payload.get("provenance")
        if not isinstance(provenance, dict) or not provenance.get("source_id"):
            errors.append("source provenance is missing")
        safety = payload.get("safety")
        if not isinstance(safety, dict) or safety.get("decision_support_only") is not True:
            errors.append("decision_support_only safety boundary is missing")

    return errors


async def _run_with_client(
    client: Client, endpoint: str, matrix: dict[str, Any]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    listing = await client.list_tools()
    available_tools = {tool.name for tool in listing.tools}
    for persona in matrix["personas"]:
        for case in persona["questions"]:
            started = time.perf_counter()
            errors: list[str] = []
            payload: dict[str, Any] = {}
            try:
                if case["tool"] not in available_tools:
                    raise AssertionError(f"tool {case['tool']!r} is not exposed")
                result = await client.call_tool(case["tool"], case["arguments"])
                payload = _payload(result)
                errors = _validate_case(case, payload)
            except Exception as exc:  # report every scenario; do not stop at the first defect
                errors = [f"{type(exc).__name__}: {exc}"]
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            rows.append(
                {
                    "persona_id": persona["id"],
                    "persona": persona["label"],
                    "case_id": case["id"],
                    "question": case["question"],
                    "tool": case["tool"],
                    "result_status": payload.get("result_status"),
                    "total_matches": payload.get("total_matches"),
                    "returned_count": payload.get("returned_count"),
                    "warnings": payload.get("warnings", []),
                    "elapsed_ms": elapsed_ms,
                    "passed": not errors,
                    "errors": errors,
                }
            )

    latencies = [row["elapsed_ms"] for row in rows]
    failures = [row for row in rows if not row["passed"]]
    persona_summary = []
    for persona in matrix["personas"]:
        selected = [row for row in rows if row["persona_id"] == persona["id"]]
        persona_summary.append(
            {
                "persona_id": persona["id"],
                "persona": persona["label"],
                "passed": sum(row["passed"] for row in selected),
                "total": len(selected),
            }
        )
    return {
        "matrix_version": matrix["version"],
        "endpoint": endpoint,
        "personas": len(matrix["personas"]),
        "questions": len(rows),
        "passed": len(rows) - len(failures),
        "failed": len(failures),
        "latency_ms": {
            "median": round(statistics.median(latencies), 1),
            "max": max(latencies),
        },
        "persona_summary": persona_summary,
        "results": rows,
    }


async def run_matrix_http(url: str, matrix: dict[str, Any]) -> dict[str, Any]:
    async with Client(streamable_http_client(url), read_timeout_seconds=30) as client:
        return await _run_with_client(client, url, matrix)


async def run_matrix_stdio(
    python: Path, data_dir: Path, cwd: Path, matrix: dict[str, Any]
) -> dict[str, Any]:
    params = StdioServerParameters(
        command=str(python),
        args=["-m", "taiwan_lab_mcp.server"],
        cwd=cwd,
        env={
            "TAIWAN_LAB_DATA_MODE": "official_snapshot",
            "TAIWAN_LAB_DATA_DIR": str(data_dir.resolve()),
            "PYTHONIOENCODING": "utf-8",
        },
    )
    endpoint = "stdio:installed-wheel"
    async with Client(stdio_client(params), mode="auto", read_timeout_seconds=30) as client:
        return await _run_with_client(client, endpoint, matrix)


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Persona scenario report",
        "",
        f"- Matrix: `{report['matrix_version']}`",
        f"- Endpoint: `{report['endpoint']}`",
        f"- Result: **{report['passed']}/{report['questions']} passed**",
        f"- Median latency: {report['latency_ms']['median']} ms",
        f"- Max latency: {report['latency_ms']['max']} ms",
        "",
        "## Persona summary",
        "",
        "| Persona | Passed |",
        "|---|---:|",
    ]
    lines.extend(
        f"| {row['persona']} | {row['passed']}/{row['total']} |"
        for row in report["persona_summary"]
    )
    lines.extend(["", "## Failures", ""])
    failures = [row for row in report["results"] if not row["passed"]]
    if not failures:
        lines.append("None.")
    else:
        for row in failures:
            lines.append(
                f"- `{row['case_id']}` {row['question']} — " + "; ".join(row["errors"])
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument("--url")
    transport.add_argument("--stdio-python", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--stdio-cwd", type=Path, default=Path.cwd())
    parser.add_argument(
        "--matrix", default="tests/scenarios/persona-scenarios-v1.json", type=Path
    )
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    if args.stdio_python:
        if args.data_dir is None:
            parser.error("--data-dir is required with --stdio-python")
        report = asyncio.run(
            run_matrix_stdio(args.stdio_python, args.data_dir, args.stdio_cwd, matrix)
        )
    else:
        report = asyncio.run(run_matrix_http(args.url, matrix))
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered, encoding="utf-8", newline="\n")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_markdown(report), encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
