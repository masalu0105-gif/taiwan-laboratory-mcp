from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Any

from ..config import DataContext
from ..importers.tfda import (
    TFDA_FIELD_NAMES,
    IvdCoverage,
    create_tfda_schema,
    finish_tfda_schema,
    insert_tfda_rows,
    tfda_curated_row,
)
from ..models import (
    TFDA_EFFECT_PREVIEW_CHARS,
    Provenance,
    SourceStatus,
    TFDARecord,
    TFDASearchRecord,
    ToolResult,
)
from ..rules.tfda import TemporalEvaluation, load_ivd_registry
from ..sources import TFDA_DEVICE
from ..tfda_store import (
    TAIPEI,
    SearchRequest,
    connect_readonly,
    evaluate_row,
    license_rows,
    matched_fields,
    read_tfda_state,
    search_rows,
)
from ..util import norm
from .base import invalid_result, load_sample, result_from_rows, unavailable_result

# Owner decisions 2026-09-15: search results are summaries; one page first held 20 rows,
# then 「20筆好像還是有點太多，還是給5筆 有需要的話可以再進一步找」.
SEARCH_PAGE_MAX = 5
_IVD_SCOPES = ("included", "excluded", "ambiguous", "unknown")
_CANDIDATE_SCOPES = ("included", "ambiguous", "unknown")
_MAIN_CATEGORIES = frozenset("ABCDEFGHIJKLMNOP")
_ALL_FIELDS = (
    "license_no",
    "name_zh",
    "name_en",
    "applicant",
    "manufacturer",
    "effect",
    "classification",
)
# IVD tools filter manufacturers through their own parameter, so the query skips both roles.
_IVD_FIELDS = ("license_no", "name_zh", "name_en", "effect", "classification")
_SAMPLE_CLASSIFICATION = ("B 血液學及病理學", "B.9225 示範品項")
_SEARCH_NOTE = "query 與 manufacturer 必須是非空字串；limit 為 1–5 的整數，offset 不得小於 0。"
_LIST_NOTE = (
    "query 必須是非空字串；limit 為 1–5 的整數，offset 不得小於 0；prefer_ivd 為布林值；"
    "prefer_main_category 與 main_category 為 A–P 單一大寫字母或 null；"
    "ivd_scope 為 included、excluded、ambiguous、unknown 或 null。"
)


def _valid_text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 200 and bool(norm(value))


def _valid_page(limit: Any, offset: Any) -> bool:
    return (
        type(limit) is int and 1 <= limit <= SEARCH_PAGE_MAX and type(offset) is int and offset >= 0
    )


def _valid_letter(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value in _MAIN_CATEGORIES)


def _sample_values(device: dict[str, Any]) -> list[str]:
    fields = dict.fromkeys(TFDA_FIELD_NAMES, "")
    fields.update(
        license_no_raw=device.get("license_no") or "",
        name_zh_raw=device.get("name_zh") or "",
        name_en_raw=device.get("name_en") or "",
        effect_raw=device.get("effect") or "",
        applicant_name_raw=device.get("applicant") or "",
        manufacturer_name_raw=device.get("manufacturer") or "",
        cancellation_status_raw=device.get("cancellation_status") or "",
        cancellation_date_raw=device.get("cancelled_at") or "",
        valid_through_raw=device.get("valid_until") or "",
        main_category_1_raw=_SAMPLE_CLASSIFICATION[0],
        sub_category_1_raw=_SAMPLE_CLASSIFICATION[1],
    )
    return [fields[name] for name in TFDA_FIELD_NAMES]


def _optional(value: str) -> str | None:
    return value or None


def _full_record(row: dict[str, Any], evaluation: TemporalEvaluation) -> TFDARecord:
    return TFDARecord(
        license_no_raw=row["license_no_raw"],
        **{name: _optional(row[name]) for name in TFDA_FIELD_NAMES[1:]},
        main_category_letters=list(row["main_category_letters"]),
        classification_codes=json.loads(row["classification_codes"]),
        ivd_scope=row["ivd_scope"],
        ivd_rule_version=row["ivd_rule_version"],
        cancellation_recorded_in_source=evaluation.cancellation_recorded_in_source,
        within_validity_period_as_of=evaluation.within_validity_period_as_of,
    )


def _summary_record(
    row: dict[str, Any], matched_by: list[str], evaluation: TemporalEvaluation
) -> TFDASearchRecord:
    effect = row["effect_raw"]
    return TFDASearchRecord(
        matched_by=matched_by,
        license_no_raw=row["license_no_raw"],
        name_zh_raw=_optional(row["name_zh_raw"]),
        name_en_raw=_optional(row["name_en_raw"]),
        applicant_name_raw=_optional(row["applicant_name_raw"]),
        manufacturer_name_raw=_optional(row["manufacturer_name_raw"]),
        manufacturer_country_raw=_optional(row["manufacturer_country_raw"]),
        risk_class_raw=_optional(row["risk_class_raw"]),
        license_kind_raw=_optional(row["license_kind_raw"]),
        main_category_letters=list(row["main_category_letters"]),
        classification_codes=json.loads(row["classification_codes"]),
        ivd_scope=row["ivd_scope"],
        cancellation_status_raw=_optional(row["cancellation_status_raw"]),
        cancellation_recorded_in_source=evaluation.cancellation_recorded_in_source,
        valid_through_raw=_optional(row["valid_through_raw"]),
        within_validity_period_as_of=evaluation.within_validity_period_as_of,
        effect_preview=effect[:TFDA_EFFECT_PREVIEW_CHARS] or None,
        effect_chars=len(effect),
        effect_truncated=len(effect) > TFDA_EFFECT_PREVIEW_CHARS,
    )


@dataclass(frozen=True)
class _Source:
    connect: Callable[[], sqlite3.Connection]
    provenance: Provenance
    status: SourceStatus | None
    coverage_detail: dict[str, Any]


class TFDAAdapter:
    def __init__(self, context: DataContext | None = None) -> None:
        self.context = context or DataContext.from_env()
        self.decisions = load_ivd_registry()
        self.devices = (
            load_sample("tfda_devices.sample.json") if self.context.mode == "sample" else []
        )

    def _as_of(self) -> date:
        now = self.context.clock() if self.context.clock else datetime.now(timezone.utc)
        return now.astimezone(TAIPEI).date()

    def _source(self, operation: str, query: dict[str, Any]) -> _Source | ToolResult:
        if self.context.mode == "sample":
            # Synthetic fixture rows go through the same curated columns and SQL as official data.
            rows = [
                tfda_curated_row(number, _sample_values(device), self.decisions)
                for number, device in enumerate(self.devices, start=1)
            ]
            coverage = IvdCoverage(self.decisions)
            for row in rows:
                coverage.add(row)

            def connect() -> sqlite3.Connection:
                connection = sqlite3.connect(":memory:")
                connection.row_factory = sqlite3.Row
                create_tfda_schema(connection)
                insert_tfda_rows(connection, rows)
                finish_tfda_schema(connection, unique_rows=False)
                return connection

            return _Source(connect, TFDA_DEVICE, None, coverage.detail())
        assert self.context.data_root is not None
        state = read_tfda_state(self.context.data_root, clock=self.context.clock)
        if state.availability != "available" or state.db_path is None or state.provenance is None:
            return unavailable_result(
                operation=operation,
                query=query,
                reason=state.reason or "no_serving_snapshot",
                note="TFDA official serving snapshot 尚未建立，或沒有通過完整性檢查。",
                source_status=state.status,
            )
        db_path = state.db_path
        return _Source(
            lambda: connect_readonly(db_path),
            state.provenance,
            state.status,
            state.coverage_detail or {},
        )

    def _respond(
        self,
        operation: str,
        request: dict[str, Any],
        source: _Source,
        total: int,
        rows: list[dict[str, Any]],
        record: Callable[[dict[str, Any], TemporalEvaluation], Any],
        *,
        limit: int,
        offset: int,
        result_status: str | None = None,
        notes: list[str] | None = None,
        warnings: list[str] | None = None,
        coverage_detail: dict[str, Any] | None = None,
        replacement_operation: str | None = None,
    ) -> ToolResult:
        as_of = self._as_of()
        evaluations: dict[int, TemporalEvaluation] = {}

        def evaluation(row: dict[str, Any]) -> TemporalEvaluation:
            key = row["source_row_number"]
            if key not in evaluations:
                evaluations[key] = evaluate_row(row, as_of)
            return evaluations[key]

        temporal = result_status in (None, "candidate_matches_available")
        return result_from_rows(
            operation=operation,
            query=request,
            rows=rows,
            total_matches=total,
            provenance=source.provenance,
            record_factory=lambda row: record(row, evaluation(row)),
            item_warnings=lambda row: list(evaluation(row).warnings),
            source_id="tfda_device",
            source_status=source.status,
            limit=limit,
            offset=offset,
            result_status=result_status,
            extra_warnings=warnings,
            extra_notes=notes,
            evaluated_as_of=as_of if temporal else None,
            evaluated_timezone="Asia/Taipei" if temporal else None,
            coverage_detail=coverage_detail,
            replacement_operation=replacement_operation,
        )

    def _summaries(
        self, operation: str, request: dict[str, Any], search: SearchRequest, **extra: Any
    ) -> ToolResult:
        source = self._source(operation, request)
        if isinstance(source, ToolResult):
            return source
        with closing(source.connect()) as connection:
            total, rows = search_rows(connection, search)
        return self._respond(
            operation,
            request,
            source,
            total,
            rows,
            lambda row, evaluation: _summary_record(
                row, matched_fields(row, search.query, search.fields), evaluation
            ),
            limit=search.limit,
            offset=search.offset,
            **extra,
        )

    def _ivd_search(
        self,
        operation: str,
        query: Any,
        manufacturer: Any,
        limit: Any,
        offset: Any,
        *,
        reviewed: bool,
    ) -> ToolResult:
        request = {"query": query, "manufacturer": manufacturer, "limit": limit, "offset": offset}
        if (
            not _valid_text(query)
            or (manufacturer is not None and not _valid_text(manufacturer))
            or not _valid_page(limit, offset)
        ):
            return invalid_result(
                operation=operation, query=request, data_mode=self.context.mode, note=_SEARCH_NOTE
            )
        source = self._source(operation, request)
        if isinstance(source, ToolResult):
            return source
        search = SearchRequest(
            query=query,
            fields=_IVD_FIELDS,
            ivd_scopes=("included",) if reviewed else _CANDIDATE_SCOPES,
            manufacturer=manufacturer,
            limit=limit,
            offset=offset,
        )
        with closing(source.connect()) as connection:
            total, rows = search_rows(connection, search)
            candidates = 0
            if reviewed and total == 0:
                candidates, _ = search_rows(
                    connection, replace(search, ivd_scopes=_CANDIDATE_SCOPES, limit=1, offset=0)
                )

        def summary(row: dict[str, Any], evaluation: TemporalEvaluation) -> TFDASearchRecord:
            return _summary_record(row, matched_fields(row, query, _IVD_FIELDS), evaluation)

        if candidates:
            return self._respond(
                operation,
                request,
                source,
                0,
                [],
                summary,
                limit=limit,
                offset=offset,
                result_status="candidate_matches_available",
                notes=[
                    "沒有逐碼審核為體外診斷（included）的許可證列符合；"
                    f"另有 {candidates} 筆候選（含未判定），請改用 search_ivd_candidates 查看。"
                ],
            )
        note = (
            "只回逐碼審核為體外診斷（included）的許可證列；ambiguous 與 unknown 請用 "
            "search_ivd_candidates。"
            if reviewed
            else "候選包含 included、ambiguous 與 unknown；unknown 表示缺分類代碼、舊制分類或"
            "不在已審核附表，不代表是或不是體外診斷。"
        )
        return self._respond(
            operation,
            request,
            source,
            total,
            rows,
            summary,
            limit=limit,
            offset=offset,
            notes=[note],
            coverage_detail=None if reviewed else source.coverage_detail,
        )

    def search_reviewed_ivd(
        self, query: Any, manufacturer: Any = None, limit: Any = 5, offset: Any = 0
    ) -> ToolResult:
        return self._ivd_search(
            "search_reviewed_ivd", query, manufacturer, limit, offset, reviewed=True
        )

    def search_ivd_candidates(
        self, query: Any, manufacturer: Any = None, limit: Any = 5, offset: Any = 0
    ) -> ToolResult:
        return self._ivd_search(
            "search_ivd_candidates", query, manufacturer, limit, offset, reviewed=False
        )

    def search_ivd(self, query: Any, manufacturer: Any = None) -> ToolResult:
        result = self.search_reviewed_ivd(query, manufacturer, 5, 0)
        payload = result.model_dump(mode="python")
        payload["operation"] = "search_ivd"
        payload["query"] = {"query": query, "manufacturer": manufacturer}
        return ToolResult.model_validate(payload)

    def get_license(self, license_no: Any) -> ToolResult:
        request = {"license_no": license_no}
        if not _valid_text(license_no):
            return invalid_result(
                operation="get_license",
                query=request,
                data_mode=self.context.mode,
                note="license_no 必須是非空字串。",
            )
        source = self._source("get_license", request)
        if isinstance(source, ToolResult):
            return source
        with closing(source.connect()) as connection:
            total, rows = license_rows(connection, license_no)
        return self._respond(
            "get_license", request, source, total, rows, _full_record, limit=20, offset=0
        )

    def find_manufacturer(self, name: Any, limit: Any = 5, offset: Any = 0) -> ToolResult:
        request = {"name": name, "limit": limit, "offset": offset}
        if not _valid_text(name) or not _valid_page(limit, offset):
            return invalid_result(
                operation="find_manufacturer",
                query=request,
                data_mode=self.context.mode,
                note="name 必須是非空字串；limit 為 1–5 的整數，offset 不得小於 0。",
            )
        return self._summaries(
            "find_manufacturer",
            request,
            SearchRequest(
                query=name,
                fields=("manufacturer",),
                rank_by_manufacturer=True,
                limit=limit,
                offset=offset,
            ),
        )

    def list_matching_license_records(
        self,
        query: Any,
        limit: Any = 5,
        offset: Any = 0,
        prefer_ivd: Any = False,
        prefer_main_category: Any = None,
        ivd_scope: Any = None,
        main_category: Any = None,
    ) -> ToolResult:
        request = {
            "query": query,
            "limit": limit,
            "offset": offset,
            "prefer_ivd": prefer_ivd,
            "prefer_main_category": prefer_main_category,
            "ivd_scope": ivd_scope,
            "main_category": main_category,
        }
        if (
            not _valid_text(query)
            or not _valid_page(limit, offset)
            or type(prefer_ivd) is not bool
            or not _valid_letter(prefer_main_category)
            or not (ivd_scope is None or ivd_scope in _IVD_SCOPES)
            or not _valid_letter(main_category)
        ):
            return invalid_result(
                operation="list_matching_license_records",
                query=request,
                data_mode=self.context.mode,
                note=_LIST_NOTE,
            )
        return self._summaries(
            "list_matching_license_records",
            request,
            SearchRequest(
                query=query,
                fields=_ALL_FIELDS,
                ivd_scopes=None if ivd_scope is None else (ivd_scope,),
                main_category=main_category,
                prefer_ivd=prefer_ivd,
                prefer_main_category=prefer_main_category,
                limit=limit,
                offset=offset,
            ),
        )

    def compare_products(self, query: Any, limit: Any = 10) -> ToolResult:
        request = {"query": query, "limit": limit}
        if not _valid_text(query) or type(limit) is not int or not 1 <= limit <= 100:
            return invalid_result(
                operation="compare_products",
                query=request,
                data_mode=self.context.mode,
                note="query 必須是非空字串；limit 為 1–100 的整數。",
            )
        source = self._source("compare_products", request)
        if isinstance(source, ToolResult):
            return source
        return self._respond(
            "compare_products",
            request,
            source,
            0,
            [],
            _full_record,
            limit=limit,
            offset=0,
            result_status="deprecated_unsupported",
            warnings=["deprecated_unsupported"],
            notes=[
                "P1.1 不提供產品比較、優劣、採購或等效判定；請改用 list_matching_license_records。"
            ],
            replacement_operation="list_matching_license_records",
        )
