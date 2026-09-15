from __future__ import annotations

from contextlib import closing
from typing import Any

from ..config import DataContext
from ..importers.cdc_ods import CDC_LABS_FIELD_NAMES
from ..models import CDCLabRecord, CDCSpecimenRecord, ToolResult
from ..sources import CDC_LABS, CDC_SPECIMEN
from ..util import contains_any, norm
from .base import invalid_result, load_sample, result_from_rows, unavailable_result

# find_authorized_lab has no paging parameters in the public contract; it keeps the
# default page and reports total_matches and truncated.
CDC_LABS_PAGE_SIZE = 20


def _specimen_record(row: dict[str, Any]) -> CDCSpecimenRecord:
    specimens = row.get("specimens") or []
    return CDCSpecimenRecord(
        disease=row.get("disease", ""),
        specimen="；".join(str(value) for value in specimens) or None,
        purpose=None,
        collection_time=row.get("collection"),
        volume_requirement=None,
        transport_method=row.get("storage_transport"),
        retention_raw=None,
        notes=row.get("note"),
    )


def _lab_record(row: dict[str, Any]) -> CDCLabRecord:
    scope = row.get("scope") or []
    return CDCLabRecord(
        certificate_no=None,
        city=row.get("city"),
        institution=row.get("name", ""),
        department=None,
        disease_code=None,
        disease_name="；".join(str(value) for value in scope) or None,
        purpose=None,
        method=None,
        address=None,
        phone=None,
        end_time=None,
        latest_annual_pt_review_raw=None,
    )


def _official_lab_record(row: dict[str, Any]) -> CDCLabRecord:
    # Raw roster values unchanged, including a blank proficiency testing review.
    return CDCLabRecord(**{name: row[name] for name in CDC_LABS_FIELD_NAMES})


def _valid_text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 200 and bool(norm(value))


class CDCAdapter:
    def __init__(self, context: DataContext | None = None) -> None:
        self.context = context or DataContext.from_env()
        if self.context.mode == "sample":
            self.specimens = load_sample("cdc_specimen.sample.json")
            self.labs = load_sample("cdc_labs.sample.json")
        else:
            self.specimens = []
            self.labs = []

    def _unavailable(self, operation: str, query: dict[str, Any]) -> ToolResult | None:
        if self.context.mode == "official_snapshot":
            return unavailable_result(
                operation=operation,
                query=query,
                note="CDC 採檢手冊正式資料尚未完成。",
            )
        return None

    def search_disease(self, query: Any) -> ToolResult:
        request = {"query": query}
        if not _valid_text(query):
            return invalid_result(
                operation="search_disease",
                query=request,
                data_mode=self.context.mode,
                note="query 必須是非空字串。",
            )
        unavailable = self._unavailable("search_disease", request)
        if unavailable is not None:
            return unavailable
        nq = norm(query)
        rows = [
            row
            for row in self.specimens
            if any(nq in norm(x) for x in [row["disease"], *row.get("aliases", [])])
        ]
        return result_from_rows(
            operation="search_disease",
            query=request,
            rows=rows,
            provenance=CDC_SPECIMEN,
            record_factory=_specimen_record,
            source_id="cdc_manual",
        )

    def get_specimen_requirement(self, disease: Any) -> ToolResult:
        result = self.search_disease(disease)
        payload = result.model_dump(mode="python")
        payload["operation"] = "get_specimen_requirement"
        payload["query"] = {"disease": disease}
        return ToolResult.model_validate(payload)

    def find_authorized_lab(self, query: Any, city: Any = None) -> ToolResult:
        request = {"query": query, "city": city}
        if not _valid_text(query) or (city is not None and not _valid_text(city)):
            return invalid_result(
                operation="find_authorized_lab",
                query=request,
                data_mode=self.context.mode,
                note="query 必須是非空字串；city 若提供也必須是非空字串。",
            )
        if self.context.mode == "sample":
            rows = [row for row in self.labs if contains_any(row, query, ["name", "scope"])]
            if city is not None:
                rows = [row for row in rows if norm(city) in norm(row.get("city"))]
            return result_from_rows(
                operation="find_authorized_lab",
                query=request,
                rows=rows,
                provenance=CDC_LABS,
                record_factory=_lab_record,
                source_id="cdc_recognized_labs",
            )
        from ..cdc_labs_store import read_cdc_labs_state, search_labs
        from ..tfda_store import connect_readonly

        assert self.context.data_root is not None
        state = read_cdc_labs_state(self.context.data_root, clock=self.context.clock)
        if state.availability != "available" or state.db_path is None or state.provenance is None:
            return unavailable_result(
                operation="find_authorized_lab",
                query=request,
                reason=state.reason or "no_serving_snapshot",
                note="疾管署認可檢驗機構名冊正式資料尚未建立，或沒有通過完整性檢查。",
                source_status=state.status,
            )
        with closing(connect_readonly(state.db_path)) as connection:
            total, rows = search_labs(
                connection, query=query, city=city, limit=CDC_LABS_PAGE_SIZE, offset=0
            )
        return result_from_rows(
            operation="find_authorized_lab",
            query=request,
            rows=rows,
            total_matches=total,
            provenance=state.provenance,
            record_factory=_official_lab_record,
            source_id="cdc_recognized_labs",
            source_status=state.status,
            limit=CDC_LABS_PAGE_SIZE,
            offset=0,
        )

    def get_lab_scope(self, query: Any) -> ToolResult:
        result = self.find_authorized_lab(query)
        payload = result.model_dump(mode="python")
        payload["operation"] = "get_lab_scope"
        payload["query"] = {"query": query}
        return ToolResult.model_validate(payload)
