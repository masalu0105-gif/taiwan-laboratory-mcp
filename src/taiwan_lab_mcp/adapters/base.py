from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from importlib.resources import files
from typing import Any

from ..canonical import sha256_json
from ..config import DataContext
from ..models import (
    Evidence,
    ItemEnvelope,
    NhiLocator,
    OdsLocator,
    Provenance,
    SourceStatus,
    TfdaLocator,
    ToolResult,
)

SAMPLE_WARNING = "sample_only：目前只有合成示範資料，不可用於採檢、健保申報或採購；正式資料需另行同步、驗證與發布。"
NHI_NOT_OFFICIAL_NOTE = "非健保署官方服務，內容以健保署公告為準。"


def data_mode() -> str:
    """Return the process mode, preserving a small compatibility helper."""

    return DataContext.from_env().mode


def load_sample(filename: str) -> list[dict]:
    context = DataContext.from_env()
    if context.mode != "sample":
        raise ValueError("Bundled sample resources are unavailable in official_snapshot mode")
    path = files("taiwan_lab_mcp").joinpath("data", filename)
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, list):
        raise ValueError("Sample dataset must be a JSON array")
    from ..models import DataRecord

    rows = []
    for raw in content:
        record = DataRecord.model_validate(raw)
        if not record.sample_only:
            raise ValueError("Bundled data must be marked sample_only=true")
        rows.append(record.model_dump(mode="json"))
    return rows


def sample_status() -> SourceStatus:
    return SourceStatus(
        serving_validation_status="not_applicable",
        serving_review_status="not_applicable",
        latest_candidate_status="none",
        stale=False,
        stale_reason_codes=[],
    )


def make_safety(operation: str) -> dict[str, bool]:
    from ..contracts import operation_spec

    return {key: True for key in operation_spec(operation)["safety"]}


def row_digest(row: dict[str, Any]) -> str:
    return sha256_json(row)


def _default_locator(source_id: str, row_number: int) -> Any:
    if source_id == "nhi_fee":
        return NhiLocator(source_row_number=row_number)
    if source_id == "tfda_device":
        return TfdaLocator(source_row_number=row_number)
    if source_id == "cdc_manual":
        from ..models import CdcLocator

        return CdcLocator(
            pdf_page=1, printed_page=None, table_section="sample", row_bbox=[0, 0, 1, 1]
        )
    if source_id == "cdc_recognized_labs":
        return OdsLocator(sheet_name="sample", expanded_row_number=row_number)
    return OdsLocator(sheet_name="sample", expanded_row_number=row_number)


def result_from_rows(
    *,
    operation: str,
    query: dict[str, Any],
    rows: Sequence[dict[str, Any]],
    provenance: Provenance,
    record_factory: Callable[[dict[str, Any]], Any],
    source_id: str,
    limit: int = 20,
    offset: int = 0,
    result_status: str | None = None,
    extra_warnings: list[str] | None = None,
    extra_notes: list[str] | None = None,
    historical_truth_supported: bool | None = None,
    evaluated_as_of: Any = None,
    evaluated_timezone: str | None = None,
    replacement_operation: str | None = None,
    source_status: SourceStatus | None = None,
) -> ToolResult:
    total = len(rows)
    page = list(rows[offset : offset + limit])
    items = [
        ItemEnvelope(
            record=record_factory(row),
            evidence=[
                Evidence(
                    artifact_id=provenance.artifacts[0].artifact_id,
                    source_row_sha256=row.get("source_row_sha256", row_digest(row)),
                    locator=_default_locator(
                        source_id,
                        int(row.get("source_row_number", index + 1)),
                    ),
                    raw_value_available=True,
                )
            ],
            item_warnings=[],
            safety=make_safety(operation),
        )
        for index, row in enumerate(page, start=offset)
    ]
    warnings = list(extra_warnings or [])
    notes = list(extra_notes or [])
    if provenance.snapshot_id is None:
        warnings.insert(0, "sample_only")
        notes.insert(0, SAMPLE_WARNING)
    if provenance.coverage_status == "review_incomplete":
        warnings.append("coverage_review_incomplete")
        notes.append(
            "NHI laboratory scope 尚未完成 reviewer 核准；目前可查全表，不宣稱完整檢驗子集。"
        )
    if provenance.source_id == "nhi_fee" and provenance.snapshot_id is not None:
        # Owner-approved PRD REL-G4 non-official service statement (2026-09-14).
        notes.append(NHI_NOT_OFFICIAL_NOTE)
    if provenance.stale:
        warnings.extend(provenance.stale_reason_codes)
        notes.append("serving snapshot 已標記 stale；使用者應重新核對目前官方來源。")
    if not page and result_status is None:
        notes.append("僅在目前 serving snapshot 內查無符合紀錄，無法據此判定官方資料不存在。")
    return ToolResult(
        operation=operation,
        query=query,
        result_status=result_status or ("ok" if page else "not_found"),
        data_mode="sample" if provenance.snapshot_id is None else "official_snapshot",
        sample_only=provenance.snapshot_id is None,
        availability="available",
        availability_reason_code=None,
        source_status=source_status
        or SourceStatus(
            serving_validation_status=(
                "not_applicable" if provenance.snapshot_id is None else "passed"
            ),
            serving_review_status=provenance.serving_review_status,
            latest_candidate_status="none",
            stale=provenance.stale,
            stale_reason_codes=provenance.stale_reason_codes,
        ),
        coverage_status=provenance.coverage_status,
        coverage_detail=None,
        items=items,
        total_matches=total,
        returned_count=len(items),
        limit=limit,
        offset=offset,
        truncated=offset + len(items) < total,
        historical_truth_supported=historical_truth_supported,
        evaluated_as_of=evaluated_as_of,
        evaluated_timezone=evaluated_timezone,
        replacement_operation=replacement_operation,
        provenance=provenance,
        snapshot_traceable=True,
        # A locally served snapshot is traceable to its captured artifact.  That
        # alone does not prove the upstream can be fetched again right now.
        currently_reproducible_from_upstream=False,
        warnings=warnings,
        notes=notes,
        safety=make_safety(operation),
    )


def invalid_result(
    *,
    operation: str,
    query: dict[str, Any],
    provenance: Provenance | None = None,
    data_mode: str | None = None,
    note: str,
) -> ToolResult:
    mode = data_mode or DataContext.from_env().mode
    is_sample = mode == "sample" and (provenance is None or provenance.snapshot_id is None)
    status = (
        sample_status()
        if is_sample
        else SourceStatus(
            serving_validation_status=(
                "not_applicable"
                if provenance is None or provenance.snapshot_id is None
                else "passed"
            ),
            serving_review_status=(
                provenance.serving_review_status if provenance else "not_applicable"
            ),
            latest_candidate_status="none",
            stale=provenance.stale if provenance else False,
            stale_reason_codes=provenance.stale_reason_codes if provenance else [],
        )
    )
    return ToolResult(
        operation=operation,
        query=query,
        result_status="invalid_request",
        data_mode="sample" if is_sample else "official_snapshot",
        sample_only=is_sample,
        availability="available",
        availability_reason_code=None,
        source_status=status,
        coverage_status=provenance.coverage_status if provenance else "unknown",
        coverage_detail=None,
        items=[],
        total_matches=0,
        returned_count=0,
        limit=20,
        offset=0,
        truncated=False,
        historical_truth_supported=None,
        evaluated_as_of=None,
        evaluated_timezone=None,
        replacement_operation=None,
        provenance=provenance,
        snapshot_traceable=provenance is not None,
        currently_reproducible_from_upstream=False,
        warnings=["invalid_request"],
        notes=[note],
        safety=make_safety(operation),
    )


def unavailable_result(
    *,
    operation: str,
    query: dict[str, Any],
    reason: str = "no_serving_snapshot",
    note: str,
    source_status: SourceStatus | None = None,
) -> ToolResult:
    return ToolResult(
        operation=operation,
        query=query,
        result_status="data_unavailable",
        data_mode="official_snapshot",
        sample_only=False,
        availability="data_unavailable",
        availability_reason_code=reason,
        source_status=source_status
        or SourceStatus(
            serving_validation_status="not_applicable",
            serving_review_status="not_applicable",
            latest_candidate_status="none",
            stale=False,
            stale_reason_codes=[],
        ),
        coverage_status="unknown",
        coverage_detail=None,
        items=[],
        total_matches=0,
        returned_count=0,
        limit=20,
        offset=0,
        truncated=False,
        historical_truth_supported=None,
        evaluated_as_of=None,
        evaluated_timezone=None,
        replacement_operation=None,
        provenance=None,
        snapshot_traceable=False,
        currently_reproducible_from_upstream=False,
        warnings=[reason],
        notes=[note, "official_snapshot 不可用時不會退回或混入 sample 資料。"],
        safety=make_safety(operation),
    )
