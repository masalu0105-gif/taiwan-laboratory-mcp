from __future__ import annotations

from typing import Any

from ..config import DataContext
from ..models import CDCLabRecord, CDCSpecimenRecord, ToolResult
from ..sources import CDC_LABS, CDC_SPECIMEN
from ..util import contains_any, norm
from .base import invalid_result, load_sample, result_from_rows, unavailable_result


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
                note="CDC official snapshot 尚未在本輪 vertical slice 實作。",
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
        unavailable = self._unavailable("find_authorized_lab", request)
        if unavailable is not None:
            return unavailable
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
