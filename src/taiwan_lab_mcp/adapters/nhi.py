from __future__ import annotations

from datetime import date
from typing import Any

from ..config import DataContext
from ..models import NHIRecord, NHISearchRecord, SourceStatus, ToolResult
from ..rules.nhi import load_aliases
from ..sources import NHI_FEE
from ..stores import OfficialState, read_nhi_state
from ..util import contains_any, norm, search_normalize
from .base import invalid_result, load_sample, result_from_rows, unavailable_result


def _sample_record(row: dict[str, Any], matched_by: list[str] | None = None) -> NHIRecord:
    return NHIRecord(
        matched_by=matched_by or ["code"],
        code_raw=row.get("code", ""),
        code_normalized=search_normalize(row.get("code")),
        points_raw=None if row.get("points") is None else str(row["points"]),
        points=row.get("points"),
        effective_start_raw=None,
        effective_start=None,
        effective_end_raw=None,
        effective_end=None,
        possible_open_end_sentinel=False,
        name_zh_raw=row.get("name_zh"),
        name_zh_search=search_normalize(row.get("name_zh")) or None,
        name_en_raw=row.get("name_en"),
        name_en_search=search_normalize(row.get("name_en")) or None,
        note_raw=row.get("note"),
        note_search=search_normalize(row.get("note")) or None,
        scope_status="review_pending",
        scope_rule_version="nhi-lab-scope-v1",
        scope_basis_locator=None,
    )


def _official_record(row: dict[str, Any], matched_by: list[str] | None = None) -> NHIRecord:
    return NHIRecord(
        matched_by=matched_by or ["code"],
        code_raw=row["code_raw"],
        code_normalized=row["code_normalized"],
        points_raw=row["points_raw"],
        points=row["points"],
        effective_start_raw=row["effective_start_raw"],
        effective_start=row["effective_start"],
        effective_end_raw=row["effective_end_raw"],
        effective_end=row["effective_end"],
        possible_open_end_sentinel=bool(row["possible_open_end_sentinel"]),
        name_zh_raw=row["name_zh_raw"],
        name_zh_search=row["name_zh_search"],
        name_en_raw=row["name_en_raw"],
        name_en_search=row["name_en_search"],
        note_raw=row["note_raw"],
        note_search=row["note_search"],
        scope_status=row["scope_status"],
        scope_rule_version=row["scope_rule_version"],
        scope_basis_locator=row["scope_basis_locator"],
    )


def _sample_summary(row: dict[str, Any], matched_by: list[str]) -> NHISearchRecord:
    return NHISearchRecord.from_note(
        row.get("note"),
        matched_by=matched_by,
        code_raw=row.get("code", ""),
        points=row.get("points"),
        effective_start=None,
        effective_end=None,
        possible_open_end_sentinel=False,
        name_zh_raw=row.get("name_zh"),
        name_en_raw=row.get("name_en"),
        scope_status="review_pending",
    )


def _official_summary(row: dict[str, Any], matched_by: list[str]) -> NHISearchRecord:
    return NHISearchRecord.from_note(
        row["note_raw"],
        matched_by=matched_by,
        code_raw=row["code_raw"],
        points=row["points"],
        effective_start=row["effective_start"],
        effective_end=row["effective_end"],
        possible_open_end_sentinel=bool(row["possible_open_end_sentinel"]),
        name_zh_raw=row["name_zh_raw"],
        name_en_raw=row["name_en_raw"],
        scope_status=row["scope_status"],
    )


# Owner decisions 2026-09-15: bounded under host output limits, then "20 筆就很夠了".
SEARCH_PAGE_MAX = 20


def _valid_text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 200 and bool(norm(value))


def _valid_page(limit: Any, offset: Any) -> bool:
    return (
        type(limit) is int and 1 <= limit <= SEARCH_PAGE_MAX and type(offset) is int and offset >= 0
    )


def _matched_by(
    row: dict[str, Any],
    query: str,
    *,
    official: bool,
    aliases: dict[str, tuple[str, ...]] | None = None,
) -> list[str]:
    normalized_query = search_normalize(query)
    fields = (
        ("code", row["code_normalized"])
        if official
        else ("code", search_normalize(row.get("code")))
    )
    values = [fields]
    if official:
        values.extend(
            [
                ("name_zh", row["name_zh_search"] or ""),
                ("name_en", row["name_en_search"] or ""),
                ("note", row["note_search"] or ""),
            ]
        )
    else:
        values.extend(
            [
                ("name_zh", search_normalize(row.get("name_zh"))),
                ("name_en", search_normalize(row.get("name_en"))),
                ("note", search_normalize(row.get("note"))),
            ]
        )
    matched = [name for name, value in values if normalized_query in value]
    if official and any(
        row["code_normalized"] == search_normalize(code)
        for code in (aliases or {}).get(normalized_query, ())
    ):
        matched.append("alias")
    return matched


def _unsupported_history(
    context: DataContext, code: Any, as_of: Any, state: OfficialState | None = None
) -> ToolResult:
    provenance = NHI_FEE if context.mode == "sample" else (state.provenance if state else None)
    if provenance is None:
        return ToolResult(
            operation="get_points",
            query={"code": code, "as_of": as_of},
            result_status="historical_query_unsupported",
            data_mode="official_snapshot",
            sample_only=False,
            availability="available",
            availability_reason_code=None,
            source_status=SourceStatus(
                serving_validation_status="not_applicable",
                serving_review_status="not_applicable",
                latest_candidate_status="none",
                stale=False,
                stale_reason_codes=[],
            ),
            coverage_status="review_incomplete",
            coverage_detail=None,
            items=[],
            total_matches=0,
            returned_count=0,
            limit=20,
            offset=0,
            truncated=False,
            historical_truth_supported=False,
            evaluated_as_of=None,
            evaluated_timezone=None,
            replacement_operation=None,
            provenance=None,
            snapshot_traceable=False,
            currently_reproducible_from_upstream=False,
            warnings=["historical_query_unsupported"],
            notes=[
                "NHI 目前只有 current serving snapshot；合法的歷史日期查詢不受支援。",
                "此拒絕不會讀取 current row，也不會退回或混入 sample 資料。",
            ],
            safety={
                "decision_support_only": True,
                "verify_current_official_source": True,
                "not_validated_for_hospital_deployment": True,
                "not_for_claim_determination": True,
            },
        )
    return result_from_rows(
        operation="get_points",
        query={"code": code, "as_of": as_of},
        rows=[],
        provenance=provenance,
        record_factory=_official_record,
        source_id="nhi_fee",
        source_status=state.status if state else None,
        result_status="historical_query_unsupported",
        extra_warnings=["historical_query_unsupported"],
        extra_notes=[
            "NHI snapshot 是現行清單，不是完整歷史資料庫；未比較 current row，也未輸出指定日期點數。"
        ],
        historical_truth_supported=False,
    )


class NHIAdapter:
    def __init__(self, context: DataContext | None = None) -> None:
        self.context = context or DataContext.from_env()
        self.aliases = load_aliases()
        self.fees = load_sample("nhi_fee.sample.json") if self.context.mode == "sample" else []

    def _state(self) -> OfficialState:
        assert self.context.data_root is not None
        return read_nhi_state(self.context.data_root, clock=self.context.clock)

    def _sample_or_unavailable(
        self, operation: str, query: dict[str, Any], note: str
    ) -> OfficialState | ToolResult | None:
        if self.context.mode == "official_snapshot":
            state = self._state()
            if state.availability != "available":
                return unavailable_result(
                    operation=operation,
                    query=query,
                    reason=state.reason or "no_serving_snapshot",
                    note=note,
                    source_status=state.status,
                )
            return state
        return None

    def search_payment_items(self, query: Any, limit: Any = 20, offset: Any = 0) -> ToolResult:
        request = {"query": query, "limit": limit, "offset": offset}
        if not _valid_text(query) or not _valid_page(limit, offset):
            return invalid_result(
                operation="search_payment_items",
                query=request,
                data_mode=self.context.mode,
                note="query 必須是非空字串；limit 為 1–20 的整數，offset 不得小於 0。",
            )
        state_or_unavailable = self._sample_or_unavailable(
            "search_payment_items", request, "NHI official serving snapshot 尚未建立。"
        )
        if isinstance(state_or_unavailable, ToolResult):
            return state_or_unavailable
        if self.context.mode == "sample":
            nq = norm(query)
            rows = [
                row
                for row in self.fees
                if contains_any(row, query, ["code", "name_zh", "name_en", "note"])
            ]
            rows = sorted(
                rows,
                key=lambda row: (0 if norm(row.get("code")) == nq else 1, norm(row.get("code"))),
            )
            return result_from_rows(
                operation="search_payment_items",
                query=request,
                rows=rows,
                provenance=NHI_FEE,
                record_factory=lambda row: _sample_summary(
                    row, _matched_by(row, query, official=False)
                ),
                source_id="nhi_fee",
                limit=limit,
                offset=offset,
            )
        assert isinstance(state_or_unavailable, OfficialState)
        state = state_or_unavailable
        nq = search_normalize(query)
        alias_codes = {search_normalize(code) for code in self.aliases.get(nq, ())}

        def rank(row: dict[str, Any]) -> tuple[int, str, str]:
            fields = [
                row["code_normalized"],
                row["name_zh_search"] or "",
                row["name_en_search"] or "",
            ]
            if nq == fields[0]:
                priority = 0
            elif nq in fields[1:] or row["code_normalized"] in alias_codes:
                priority = 1
            elif any(field.startswith(nq) for field in fields):
                priority = 2
            else:
                priority = 3
            return priority, row["code_normalized"], row["source_row_sha256"]

        rows = [
            row
            for row in state.rows
            if any(
                nq in (row[field] or "")
                for field in ("code_normalized", "name_zh_search", "name_en_search", "note_search")
            )
            or row["code_normalized"] in alias_codes
        ]
        match_by = {
            row["source_row_sha256"]: _matched_by(row, query, official=True, aliases=self.aliases)
            for row in rows
        }
        return result_from_rows(
            operation="search_payment_items",
            query=request,
            rows=sorted(rows, key=rank),
            provenance=state.provenance,
            record_factory=lambda row: _official_summary(
                row, match_by.get(row["source_row_sha256"], ["code"])
            ),
            source_id="nhi_fee",
            source_status=state.status,
            limit=limit,
            offset=offset,
        )

    def search_lab_code(self, query: Any) -> ToolResult:
        result = self.search_payment_items(query, 20, 0)
        payload = result.model_dump(mode="python")
        payload["operation"] = "search_lab_code"
        payload["query"] = {"query": query}
        return ToolResult.model_validate(payload)

    def get_points(self, code: Any, as_of: Any = None) -> ToolResult:
        request = {"code": code, "as_of": as_of}
        if not _valid_text(code):
            return invalid_result(
                operation="get_points",
                query=request,
                data_mode=self.context.mode,
                note="code 必須是非空字串。",
            )
        if as_of is not None:
            if not isinstance(as_of, str) or not as_of or len(as_of) != 10:
                return invalid_result(
                    operation="get_points",
                    query=request,
                    data_mode=self.context.mode,
                    note="as_of 必須是 null 或嚴格 YYYY-MM-DD。",
                )
            try:
                date.fromisoformat(as_of)
            except ValueError:
                return invalid_result(
                    operation="get_points",
                    query=request,
                    data_mode=self.context.mode,
                    note="as_of 必須是有效的 Gregorian calendar date。",
                )
            state = self._state() if self.context.mode == "official_snapshot" else None
            return _unsupported_history(self.context, code, as_of, state)

        state_or_unavailable = self._sample_or_unavailable(
            "get_points", request, "NHI official serving snapshot 尚未建立。"
        )
        if isinstance(state_or_unavailable, ToolResult):
            return state_or_unavailable
        if self.context.mode == "sample":
            rows = [row for row in self.fees if norm(row.get("code")) == norm(code)]
            return result_from_rows(
                operation="get_points",
                query=request,
                rows=rows,
                provenance=NHI_FEE,
                record_factory=_sample_record,
                source_id="nhi_fee",
                extra_notes=["支付點數單位是點；不換算為新臺幣，也不判定個案可申報。"],
            )
        assert isinstance(state_or_unavailable, OfficialState)
        state = state_or_unavailable
        rows = [row for row in state.rows if row["code_normalized"] == search_normalize(code)]
        return result_from_rows(
            operation="get_points",
            query=request,
            rows=rows,
            provenance=state.provenance,
            record_factory=lambda row: _official_record(row, ["code"]),
            source_id="nhi_fee",
            source_status=state.status,
            extra_notes=["支付點數單位是點；不換算為新臺幣，也不判定個案可申報。"],
        )

    def get_payment_rule(self, query: Any) -> ToolResult:
        request = {"query": query}
        if not _valid_text(query):
            return invalid_result(
                operation="get_payment_rule",
                query=request,
                data_mode=self.context.mode,
                note="query 必須是非空字串。",
            )
        state_or_unavailable = self._sample_or_unavailable(
            "get_payment_rule", request, "NHI official serving snapshot 尚未建立。"
        )
        if isinstance(state_or_unavailable, ToolResult):
            return state_or_unavailable
        if self.context.mode == "sample":
            rows = [row for row in self.fees if norm(row.get("code")) == norm(query)]
            return result_from_rows(
                operation="get_payment_rule",
                query=request,
                rows=rows,
                provenance=NHI_FEE,
                record_factory=lambda row: _sample_record(row, ["code"]),
                source_id="nhi_fee",
                extra_notes=["此 operation 只按 exact code 查詢備註，不作名稱搜尋或個案申報判定。"],
            )
        assert isinstance(state_or_unavailable, OfficialState)
        state = state_or_unavailable
        rows = [row for row in state.rows if row["code_normalized"] == search_normalize(query)]
        return result_from_rows(
            operation="get_payment_rule",
            query=request,
            rows=rows,
            provenance=state.provenance,
            record_factory=lambda row: _official_record(row, ["code"]),
            source_id="nhi_fee",
            source_status=state.status,
            extra_notes=["此 operation 只按 exact code 查詢備註，不作名稱搜尋或個案申報判定。"],
        )
