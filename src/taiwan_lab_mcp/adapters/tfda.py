from __future__ import annotations

from typing import Any

from ..config import DataContext
from ..models import TFDARecord, ToolResult
from ..sources import TFDA_DEVICE
from ..util import contains_any, norm
from .base import invalid_result, load_sample, result_from_rows, unavailable_result


def _sample_record(row: dict[str, Any]) -> TFDARecord:
    return TFDARecord(
        license_no=row.get("license_no", ""),
        name_zh=row.get("name_zh"),
        name_en=row.get("name_en"),
        effect=row.get("effect"),
        applicant=row.get("applicant"),
        manufacturer=row.get("manufacturer"),
        factory_address=None,
        country=None,
        process=None,
        source_cancellation_status_raw=row.get("cancellation_status"),
        source_cancellation_date_raw=row.get("cancelled_at"),
        valid_through_raw=row.get("valid_until"),
        ivd_scope="included",
        classification_code="B.9225",
    )


def _valid_text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 200 and bool(norm(value))


def _valid_page(limit: Any, offset: Any) -> bool:
    return type(limit) is int and 1 <= limit <= 100 and type(offset) is int and offset >= 0


class TFDAAdapter:
    def __init__(self, context: DataContext | None = None) -> None:
        self.context = context or DataContext.from_env()
        self.devices = (
            load_sample("tfda_devices.sample.json") if self.context.mode == "sample" else []
        )

    def _unavailable(self, operation: str, query: dict[str, Any]) -> ToolResult | None:
        if self.context.mode == "official_snapshot":
            return unavailable_result(
                operation=operation,
                query=query,
                note="TFDA official snapshot 尚未在本輪 vertical slice 實作。",
            )
        return None

    def _search(
        self, operation: str, query: Any, manufacturer: Any = None, limit: Any = 20, offset: Any = 0
    ) -> ToolResult:
        request = {"query": query, "manufacturer": manufacturer, "limit": limit, "offset": offset}
        if not _valid_text(query) or (manufacturer is not None and not _valid_text(manufacturer)):
            return invalid_result(
                operation=operation,
                query=request,
                data_mode=self.context.mode,
                note="query 與 manufacturer 必須是非空字串。",
            )
        if not _valid_page(limit, offset):
            return invalid_result(
                operation=operation,
                query=request,
                data_mode=self.context.mode,
                note="limit 為 1–100 的整數，offset 不得小於 0。",
            )
        unavailable = self._unavailable(operation, request)
        if unavailable is not None:
            return unavailable
        rows = [
            row
            for row in self.devices
            if contains_any(
                row, query, ["license_no", "name_zh", "name_en", "effect", "manufacturer"]
            )
        ]
        if manufacturer is not None:
            rows = [row for row in rows if norm(manufacturer) in norm(row.get("manufacturer"))]
        result = result_from_rows(
            operation=operation,
            query=request,
            rows=rows,
            provenance=TFDA_DEVICE,
            record_factory=_sample_record,
            source_id="tfda_device",
            limit=limit,
            offset=offset,
            extra_warnings=["ivd_review_incomplete"],
            extra_notes=[
                "sample IVD classification is synthetic and not a procurement or equivalence decision."
            ],
        )
        return result

    def search_reviewed_ivd(
        self, query: Any, manufacturer: Any = None, limit: Any = 20, offset: Any = 0
    ) -> ToolResult:
        return self._search("search_reviewed_ivd", query, manufacturer, limit, offset)

    def search_ivd_candidates(
        self, query: Any, manufacturer: Any = None, limit: Any = 20, offset: Any = 0
    ) -> ToolResult:
        return self._search("search_ivd_candidates", query, manufacturer, limit, offset)

    def search_ivd(self, query: Any, manufacturer: Any = None) -> ToolResult:
        result = self.search_reviewed_ivd(query, manufacturer, 20, 0)
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
        unavailable = self._unavailable("get_license", request)
        if unavailable is not None:
            return unavailable
        rows = [row for row in self.devices if norm(row.get("license_no")) == norm(license_no)]
        return result_from_rows(
            operation="get_license",
            query=request,
            rows=rows,
            provenance=TFDA_DEVICE,
            record_factory=_sample_record,
            source_id="tfda_device",
        )

    def find_manufacturer(self, name: Any) -> ToolResult:
        request = {"name": name}
        if not _valid_text(name):
            return invalid_result(
                operation="find_manufacturer",
                query=request,
                data_mode=self.context.mode,
                note="name 必須是非空字串。",
            )
        unavailable = self._unavailable("find_manufacturer", request)
        if unavailable is not None:
            return unavailable
        rows = [row for row in self.devices if norm(name) in norm(row.get("manufacturer"))]
        return result_from_rows(
            operation="find_manufacturer",
            query=request,
            rows=rows,
            provenance=TFDA_DEVICE,
            record_factory=_sample_record,
            source_id="tfda_device",
        )

    def list_matching_license_records(self, query: Any, limit: Any = 10) -> ToolResult:
        request = {"query": query, "limit": limit}
        if not _valid_text(query) or type(limit) is not int or not 1 <= limit <= 100:
            return invalid_result(
                operation="list_matching_license_records",
                query=request,
                data_mode=self.context.mode,
                note="query 必須是非空字串；limit 為 1–100 的整數。",
            )
        unavailable = self._unavailable("list_matching_license_records", request)
        if unavailable is not None:
            return unavailable
        rows = [
            row
            for row in self.devices
            if contains_any(
                row, query, ["license_no", "name_zh", "name_en", "effect", "manufacturer"]
            )
        ]
        return result_from_rows(
            operation="list_matching_license_records",
            query=request,
            rows=rows,
            provenance=TFDA_DEVICE,
            record_factory=_sample_record,
            source_id="tfda_device",
            limit=limit,
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
        unavailable = self._unavailable("compare_products", request)
        if unavailable is not None:
            return unavailable
        return result_from_rows(
            operation="compare_products",
            query=request,
            rows=[],
            provenance=TFDA_DEVICE,
            record_factory=_sample_record,
            source_id="tfda_device",
            limit=limit,
            result_status="deprecated_unsupported",
            replacement_operation="list_matching_license_records",
            extra_warnings=["deprecated_unsupported"],
            extra_notes=[
                "P1.1 不提供產品比較、優劣、採購或等效判定；請改用 list_matching_license_records。"
            ],
        )
