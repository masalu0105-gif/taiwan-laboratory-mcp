from __future__ import annotations

import json
import os
from importlib.resources import files

from ..models import DataRecord, Provenance, ToolResult

SAMPLE_WARNING = (
    "sample_only：目前只有合成示範資料，不可用於採檢、健保申報或採購；正式資料同步尚未實作。"
)


def data_mode() -> str:
    mode = os.environ.get("TAIWAN_LAB_DATA_MODE", "sample").strip().lower()
    if mode != "sample":
        raise ValueError("Only sample mode is implemented; official data sync is not available")
    return mode


def load_sample(filename: str) -> list[dict]:
    data_mode()
    path = files("taiwan_lab_mcp").joinpath("data", filename)
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, list):
        raise ValueError("Sample dataset must be a JSON array")
    rows = []
    for raw in content:
        record = DataRecord.model_validate(raw)
        if not record.sample_only:
            raise ValueError("Bundled data must be marked sample_only=true")
        rows.append(record.model_dump(mode="json"))
    return rows


def sample_result(query: str, rows: list[dict], source: Provenance) -> ToolResult:
    notes = [SAMPLE_WARNING]
    if not rows:
        notes.append("僅在此示範資料集內查無符合紀錄，無法據此判定官方資料不存在。")
    return ToolResult(
        query=query,
        status="sample_only" if rows else "not_found",
        items=rows,
        provenance=[source],
        notes=notes,
    )
