from __future__ import annotations

import json
from contextlib import closing
from typing import Any

from ..config import DataContext
from ..importers.cdc_manual_layout import (
    CDC_RECEIVING_UNIT_FIELDS,
    CDC_SPECIMEN_FIELDS,
    CDC_TESTING_LOCATION_FIELDS,
)
from ..importers.cdc_ods import CDC_LABS_FIELD_NAMES
from ..models import (
    CDCLabRecord,
    CDCReceivingUnitContact,
    CDCSpecimenRecord,
    CDCTestingLocationRecord,
    Evidence,
    ToolResult,
)
from ..sources import CDC_LABS, CDC_SPECIMEN
from ..util import contains_any, norm
from .base import invalid_result, load_sample, result_from_rows, unavailable_result

# Owner 2026-09-15: 「A 加翻頁」, then 「一次 20 筆」 after a simulation showed five rows often
# hold only two or three hospitals, because one hospital fills a row per method.
CDC_LABS_PAGE_MAX = 20
_LAB_SEARCH_NOTE = (
    "query 必須是非空字串；city 若提供也必須是非空字串；limit 為 1–20 的整數，offset 不得小於 0。"
)


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


def _official_specimen_record(row: dict[str, Any]) -> CDCSpecimenRecord:
    # Owner 2026-09-15 chose B (OD-15): answers read the display text; the database keeps the raw
    # cell text and the row hash for source checks.
    return CDCSpecimenRecord(**{name: row[f"{name}_display"] for name in CDC_SPECIMEN_FIELDS})


def _sample_testing_location_record(row: dict[str, Any]) -> CDCTestingLocationRecord:
    contacts = row.get("receiving_unit_contacts") or []
    return CDCTestingLocationRecord(
        disease=row.get("disease", ""),
        collecting_unit=row.get("collecting_unit"),
        specimen=row.get("specimen"),
        method=row.get("method"),
        turnaround_raw=row.get("turnaround_raw"),
        testing_period_raw=row.get("testing_period_raw"),
        receiving_unit=row.get("receiving_unit"),
        bsl_raw=row.get("bsl_raw"),
        notes=row.get("notes"),
        receiving_unit_contacts=[CDCReceivingUnitContact(**contact) for contact in contacts],
    )


def _testing_location_record(row: dict[str, Any]) -> CDCTestingLocationRecord:
    return CDCTestingLocationRecord(
        **{name: row[f"{name}_display"] for name in CDC_TESTING_LOCATION_FIELDS},
        receiving_unit_contacts=[
            CDCReceivingUnitContact(
                **{name: unit[f"{name}_display"] for name in CDC_RECEIVING_UNIT_FIELDS}
            )
            for unit in row["receiving_unit_contacts"]
        ],
    )


def _contact_evidence(row: dict[str, Any]) -> list[Evidence]:
    """Where each quoted 7.9 contact was read from, so it can be checked in the manual."""

    from ..models import CdcLocator

    return [
        Evidence(
            artifact_id="cdc-manual-pdf",
            source_row_sha256=unit["source_row_sha256"],
            locator=CdcLocator(
                pdf_page=int(unit["pdf_page"]),
                printed_page=unit["printed_page"],
                table_section=unit["table_section"],
                row_bbox=json.loads(unit["row_bbox"]),
            ),
            raw_value_available=True,
        )
        for unit in row["receiving_unit_contacts"]
    ]


def _official_lab_record(row: dict[str, Any]) -> CDCLabRecord:
    # Raw roster values unchanged, including a blank proficiency testing review.
    return CDCLabRecord(**{name: row[name] for name in CDC_LABS_FIELD_NAMES})


def _valid_text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 200 and bool(norm(value))


def _valid_page(limit: Any, offset: Any) -> bool:
    return (
        type(limit) is int
        and 1 <= limit <= CDC_LABS_PAGE_MAX
        and type(offset) is int
        and offset >= 0
    )


class CDCAdapter:
    def __init__(self, context: DataContext | None = None) -> None:
        self.context = context or DataContext.from_env()
        if self.context.mode == "sample":
            self.specimens = load_sample("cdc_specimen.sample.json")
            self.labs = load_sample("cdc_labs.sample.json")
            self.testing_locations = load_sample("cdc_testing_location.sample.json")
        else:
            self.specimens = []
            self.labs = []
            self.testing_locations = []

    def _official_specimens(self, query: str, request: dict[str, Any]) -> ToolResult:
        from ..cdc_manual_store import read_cdc_manual_state, search_specimen_rows
        from ..tfda_store import connect_readonly

        assert self.context.data_root is not None
        state = read_cdc_manual_state(self.context.data_root, clock=self.context.clock)
        if state.availability != "available" or state.db_path is None or state.provenance is None:
            return unavailable_result(
                operation="search_disease",
                query=request,
                reason=state.reason or "no_serving_snapshot",
                note="疾管署採檢手冊正式資料尚未建立，或沒有通過完整性檢查。",
                source_status=state.status,
            )
        with closing(connect_readonly(state.db_path)) as connection:
            rows = search_specimen_rows(connection, query=query)
        return result_from_rows(
            operation="search_disease",
            query=request,
            rows=rows,
            provenance=state.provenance,
            record_factory=_official_specimen_record,
            source_id="cdc_manual",
            source_status=state.status,
        )

    def search_disease(self, query: Any) -> ToolResult:
        request = {"query": query}
        if not _valid_text(query):
            return invalid_result(
                operation="search_disease",
                query=request,
                data_mode=self.context.mode,
                note="query 必須是非空字串。",
            )
        if self.context.mode == "official_snapshot":
            return self._official_specimens(query, request)
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

    def get_testing_location(self, disease: Any) -> ToolResult:
        """Chapter 7: which unit receives the specimen, by which method, and how long it takes."""

        from ..cdc_manual_store import read_cdc_manual_state, search_testing_location_rows
        from ..tfda_store import connect_readonly

        request = {"disease": disease}
        if not _valid_text(disease):
            return invalid_result(
                operation="get_testing_location",
                query=request,
                data_mode=self.context.mode,
                note="disease 必須是非空字串。",
            )
        if self.context.mode == "sample":
            nq = norm(disease)
            rows = [row for row in self.testing_locations if nq in norm(row["disease"])]
            return result_from_rows(
                operation="get_testing_location",
                query=request,
                rows=rows,
                provenance=CDC_SPECIMEN,
                record_factory=_sample_testing_location_record,
                source_id="cdc_manual",
            )
        assert self.context.data_root is not None
        state = read_cdc_manual_state(self.context.data_root, clock=self.context.clock)
        if state.availability != "available" or state.db_path is None or state.provenance is None:
            return unavailable_result(
                operation="get_testing_location",
                query=request,
                reason=state.reason or "no_serving_snapshot",
                note="疾管署採檢手冊正式資料尚未建立，或沒有通過完整性檢查。",
                source_status=state.status,
            )
        with closing(connect_readonly(state.db_path)) as connection:
            rows = search_testing_location_rows(connection, query=disease)
        return result_from_rows(
            operation="get_testing_location",
            query=request,
            rows=rows,
            provenance=state.provenance,
            record_factory=_testing_location_record,
            source_id="cdc_manual",
            source_status=state.status,
            extra_evidence=_contact_evidence,
        )

    def find_authorized_lab(
        self, query: Any, city: Any = None, limit: Any = CDC_LABS_PAGE_MAX, offset: Any = 0
    ) -> ToolResult:
        request = {"query": query, "city": city, "limit": limit, "offset": offset}
        if (
            not _valid_text(query)
            or (city is not None and not _valid_text(city))
            or not _valid_page(limit, offset)
        ):
            return invalid_result(
                operation="find_authorized_lab",
                query=request,
                data_mode=self.context.mode,
                note=_LAB_SEARCH_NOTE,
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
                limit=limit,
                offset=offset,
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
                connection, query=query, city=city, limit=limit, offset=offset
            )
            if not rows and offset > 0:
                # A page past the last match still reports how many matches exist.
                total, _ = search_labs(connection, query=query, city=city, limit=1, offset=0)
        return result_from_rows(
            operation="find_authorized_lab",
            query=request,
            rows=rows,
            total_matches=total,
            provenance=state.provenance,
            record_factory=_official_lab_record,
            source_id="cdc_recognized_labs",
            source_status=state.status,
            limit=limit,
            offset=offset,
        )

    def get_lab_scope(self, query: Any) -> ToolResult:
        result = self.find_authorized_lab(query, None, CDC_LABS_PAGE_MAX, 0)
        payload = result.model_dump(mode="python")
        payload["operation"] = "get_lab_scope"
        payload["query"] = {"query": query}
        return ToolResult.model_validate(payload)
