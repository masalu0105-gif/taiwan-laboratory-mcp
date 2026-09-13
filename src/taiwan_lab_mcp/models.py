from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


class LegacyProvenance(BaseModel):
    """Loader-only metadata model for the v0.1.1 bundled sample files."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_name: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    version: str = Field(min_length=1)
    updated_at: date | None
    updated_at_note: str | None = None
    method: Literal["synthetic", "manual_review", "structured_import"]
    locator: str = Field(min_length=1)
    retrieved_at: datetime | None = None
    license: str | None = None
    license_url: str | None = None

    @model_validator(mode="after")
    def validate_origin(self) -> LegacyProvenance:
        if self.updated_at is None and not (self.updated_at_note or "").strip():
            raise ValueError("Unknown updated_at requires an explanation")
        if self.retrieved_at is not None and self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return self


class DataRecord(BaseModel):
    """Compatibility model used only while reading bundled synthetic fixtures."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    source_url: str
    version: str = Field(min_length=1)
    updated_at: date | None
    sample_only: StrictBool
    provenance: LegacyProvenance

    @model_validator(mode="after")
    def validate_metadata(self) -> DataRecord:
        for field in ("source_url", "version", "updated_at"):
            if getattr(self, field) != getattr(self.provenance, field):
                raise ValueError(f"{field} must match provenance")
        if self.sample_only:
            if self.provenance.method != "synthetic":
                raise ValueError("Samples must identify their synthetic origin")
        elif (
            self.provenance.method == "synthetic"
            or self.provenance.retrieved_at is None
            or not (self.provenance.license or "").strip()
            or self.provenance.license_url is None
        ):
            raise ValueError("Official records require retrieval and license metadata")
        return self


class OfficialContentDate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value_raw: str = Field(min_length=1)
    precision: Literal["day", "month", "year", "unknown"]
    timezone_known: StrictBool


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    storage_scope: Literal["package_resource", "data_root"]
    data_root_relative_path: str | None
    official_url: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_artifact_available: StrictBool


class Provenance(BaseModel):
    """Strict public provenance contract shared by every query result."""

    model_config = ConfigDict(extra="forbid")

    source_id: Literal["cdc_manual", "cdc_recognized_labs", "nhi_fee", "tfda_device"]
    source_name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    landing_url: str = Field(min_length=1)
    resource_url: str = Field(min_length=1)
    snapshot_id: str | None
    curated_build_id: str | None
    official_version_raw: str | None
    official_content_date: OfficialContentDate | None
    retrieved_at: datetime
    artifacts: list[ArtifactReference]
    parser_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    rule_bundle_version: str = Field(min_length=1)
    license_name: str | None
    license_url: str | None
    attribution: str = Field(min_length=1)
    coverage_status: Literal["complete", "review_incomplete", "unknown"]
    stale: StrictBool
    stale_reason_codes: list[
        Literal[
            "upstream_check_overdue",
            "upstream_verification_failed",
            "newer_candidate_pending_review",
            "newer_candidate_rejected",
            "newer_candidate_awaiting_publish",
        ]
    ]
    last_check_at: datetime | None
    serving_review_status: Literal["not_applicable", "approved"]


class NhiLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locator_type: Literal["nhi_row"] = "nhi_row"
    source_row_number: int = Field(ge=1)


class TfdaLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locator_type: Literal["tfda_row"] = "tfda_row"
    source_row_number: int = Field(ge=1)


class CdcLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locator_type: Literal["cdc_pdf_row"] = "cdc_pdf_row"
    pdf_page: int = Field(ge=1)
    printed_page: int | None
    table_section: str = Field(min_length=1)
    row_bbox: list[int] = Field(min_length=4, max_length=4)


class OdsLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locator_type: Literal["ods_row"] = "ods_row"
    sheet_name: str = Field(min_length=1)
    expanded_row_number: int = Field(ge=1)


Locator = Union[NhiLocator, TfdaLocator, CdcLocator, OdsLocator]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    source_row_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: Locator = Field(discriminator="locator_type")
    raw_value_available: StrictBool


class NHIRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: Literal["nhi_fee"] = "nhi_fee"
    matched_by: list[Literal["code", "name_zh", "name_en", "alias", "note"]] = Field(min_length=1)
    code_raw: str
    code_normalized: str
    points_raw: str | None
    points: int | None
    effective_start_raw: str | None
    effective_start: date | None
    effective_end_raw: str | None
    effective_end: date | None
    possible_open_end_sentinel: StrictBool
    name_zh_raw: str | None
    name_zh_search: str | None
    name_en_raw: str | None
    name_en_search: str | None
    note_raw: str | None
    note_search: str | None
    scope_status: Literal["in_scope", "out_of_scope", "review_pending"]
    scope_rule_version: str = Field(min_length=1)
    scope_basis_locator: str | None


class CDCSpecimenRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: Literal["cdc_specimen"] = "cdc_specimen"
    disease: str
    specimen: str | None
    purpose: str | None
    collection_time: str | None
    volume_requirement: str | None
    transport_method: str | None
    retention_raw: str | None
    notes: str | None


class CDCLabRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: Literal["cdc_recognized_lab"] = "cdc_recognized_lab"
    certificate_no: str | None
    city: str | None
    institution: str
    department: str | None
    disease_code: str | None
    disease_name: str | None
    purpose: str | None
    method: str | None
    address: str | None
    phone: str | None
    end_time: str | None
    latest_annual_pt_review_raw: str | None


class TFDARecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: Literal["tfda_device"] = "tfda_device"
    license_no: str
    name_zh: str | None
    name_en: str | None
    effect: str | None
    applicant: str | None
    manufacturer: str | None
    factory_address: str | None
    country: str | None
    process: str | None
    source_cancellation_status_raw: str | None
    source_cancellation_date_raw: str | None
    valid_through_raw: str | None
    ivd_scope: Literal["included", "excluded", "ambiguous", "unknown"]
    classification_code: str | None


Record = Union[NHIRecord, CDCSpecimenRecord, CDCLabRecord, TFDARecord]


class ItemEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: Record = Field(discriminator="record_type")
    evidence: list[Evidence] = Field(min_length=1)
    item_warnings: list[str]
    safety: dict[str, StrictBool]


class SourceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    serving_validation_status: Literal["not_applicable", "passed"]
    serving_review_status: Literal["not_applicable", "approved"]
    latest_candidate_status: Literal[
        "none", "validating", "review_pending", "rejected", "publishable"
    ]
    stale: StrictBool
    stale_reason_codes: list[
        Literal[
            "upstream_check_overdue",
            "upstream_verification_failed",
            "newer_candidate_pending_review",
            "newer_candidate_rejected",
            "newer_candidate_awaiting_publish",
        ]
    ]


OperationName = Literal[
    "get_data_status",
    "search_disease",
    "get_specimen_requirement",
    "get_collection_method",
    "get_container",
    "get_transport_requirement",
    "get_submission_rule",
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
    "standards_status",
    "eqa_status",
]


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["public-contract-v1"] = "public-contract-v1"
    operation: OperationName
    query: dict[str, Any]
    result_status: Literal[
        "ok",
        "not_found",
        "data_unavailable",
        "invalid_request",
        "historical_query_unsupported",
        "candidate_matches_available",
        "deprecated_unsupported",
    ]
    data_mode: Literal["sample", "official_snapshot"]
    sample_only: StrictBool
    availability: Literal["available", "data_unavailable"]
    availability_reason_code: (
        Literal[
            "no_serving_snapshot",
            "serving_integrity_failure",
            "operational_status_integrity_failure",
        ]
        | None
    )
    source_status: SourceStatus
    coverage_status: Literal["complete", "review_incomplete", "unknown"]
    coverage_detail: dict[str, Any] | None
    items: list[ItemEnvelope]
    total_matches: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    truncated: StrictBool
    historical_truth_supported: StrictBool | None
    evaluated_as_of: date | None
    evaluated_timezone: str | None
    replacement_operation: OperationName | None
    provenance: Provenance | None
    snapshot_traceable: StrictBool
    currently_reproducible_from_upstream: StrictBool
    warnings: list[str]
    notes: list[str]
    safety: dict[str, StrictBool]

    @field_validator("safety")
    @classmethod
    def strict_safety_values(cls, value: dict[str, StrictBool]) -> dict[str, StrictBool]:
        if any(type(flag) is not bool for flag in value.values()):
            raise ValueError("safety values must be strict booleans")
        return value

    @model_validator(mode="after")
    def validate_result_invariants(self) -> ToolResult:
        from .contracts import operation_spec

        spec = operation_spec(self.operation)
        expected_query_keys = {parameter["name"] for parameter in spec["parameters"]}
        if set(self.query) != expected_query_keys:
            raise ValueError("query keys must match the public contract")
        expected_safety = {key: True for key in spec["safety"]}
        if self.safety != expected_safety:
            raise ValueError("safety keys must match the public contract")
        if any(item.safety != expected_safety for item in self.items):
            raise ValueError("item safety must match the public contract")
        if self.returned_count != len(self.items):
            raise ValueError("returned_count must equal item count")
        if self.total_matches < self.returned_count:
            raise ValueError("total_matches cannot be smaller than returned_count")
        if self.truncated != (self.offset + self.returned_count < self.total_matches):
            raise ValueError("truncated does not match the bounded result")
        if self.availability == "data_unavailable":
            if (
                self.result_status != "data_unavailable"
                or self.items
                or self.provenance is not None
            ):
                raise ValueError("unavailable results cannot contain data")
            if self.availability_reason_code is None:
                raise ValueError("unavailable results require a reason code")
        elif self.availability_reason_code is not None:
            raise ValueError("available results cannot have an availability failure")
        if self.availability == "available" and self.result_status == "data_unavailable":
            raise ValueError("available result cannot be data_unavailable")
        if self.data_mode == "sample" and not self.sample_only:
            raise ValueError("sample mode requires sample_only=true")
        if self.data_mode == "official_snapshot" and self.sample_only:
            raise ValueError("official mode requires sample_only=false")
        if self.availability == "available" and self.snapshot_traceable != (
            self.provenance is not None
        ):
            raise ValueError("snapshot_traceable must match provenance availability")
        if self.provenance is None and self.items:
            raise ValueError("items require provenance")
        if self.provenance is not None:
            snapshot_ids = (
                self.provenance.snapshot_id,
                self.provenance.curated_build_id,
            )
            if self.data_mode == "sample" and any(value is not None for value in snapshot_ids):
                raise ValueError("sample provenance IDs must be null")
            if self.data_mode == "official_snapshot" and self.availability == "available":
                if any(not isinstance(value, str) or not value.strip() for value in snapshot_ids):
                    raise ValueError("official provenance IDs must be non-empty and paired")
            provenance_artifacts = {artifact.artifact_id for artifact in self.provenance.artifacts}
            if not provenance_artifacts:
                raise ValueError("provenance must declare artifacts")
            if any(
                evidence.artifact_id not in provenance_artifacts
                for item in self.items
                for evidence in item.evidence
            ):
                raise ValueError("evidence artifact must be declared in provenance")
        if self.provenance is not None and self.coverage_status != self.provenance.coverage_status:
            raise ValueError("coverage status must match provenance")
        if self.provenance is not None:
            if self.source_status.serving_review_status != self.provenance.serving_review_status:
                raise ValueError("source status review must match provenance")
            if self.source_status.stale_reason_codes != self.provenance.stale_reason_codes:
                raise ValueError("source status stale reasons must match provenance")
        if self.source_status.stale != (bool(self.provenance and self.provenance.stale)):
            raise ValueError("source status and provenance stale values must match")
        if self.source_status.stale != bool(self.source_status.stale_reason_codes):
            raise ValueError("stale reason codes must match stale")
        if self.result_status == "historical_query_unsupported":
            if self.items or self.historical_truth_supported is not False:
                raise ValueError("historical rejection cannot contain current items")
        elif self.historical_truth_supported is not None:
            raise ValueError("non-historical result must not claim history")
        if self.result_status == "deprecated_unsupported" and self.items:
            raise ValueError("deprecated operation must return no items")
        return self

    @property
    def count(self) -> int:
        """Non-serialized convenience property retained for Python callers."""

        return len(self.items)

    @property
    def status(self) -> str:
        """Legacy Python convenience; never appears in the public JSON contract."""

        return self.result_status


class ContentAgeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    basis_field: str = Field(min_length=1)
    basis_value_raw: str = Field(min_length=1)
    age_days: int = Field(ge=0)
    threshold_version: str = Field(min_length=1)


class SourceDataStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: Literal["cdc_manual", "cdc_recognized_labs", "nhi_fee", "tfda_device"]
    availability: Literal["available", "data_unavailable"]
    availability_reason_code: (
        Literal[
            "no_serving_snapshot",
            "serving_integrity_failure",
            "operational_status_integrity_failure",
        ]
        | None
    )
    serving_snapshot_id: str | None
    serving_curated_build_id: str | None
    serving_validation_status: Literal["not_applicable", "passed"]
    serving_review_status: Literal["not_applicable", "approved"]
    latest_candidate_id: str | None
    latest_candidate_status: Literal[
        "none", "validating", "review_pending", "rejected", "publishable"
    ]
    coverage_status: Literal["complete", "review_incomplete", "unknown"]
    last_check_at: datetime | None
    last_successful_check_at: datetime | None
    last_successful_publish_at: datetime | None
    official_content_date: OfficialContentDate | None
    latest_seen_version: str | None
    stale: StrictBool
    stale_reason_codes: list[
        Literal[
            "upstream_check_overdue",
            "upstream_verification_failed",
            "newer_candidate_pending_review",
            "newer_candidate_rejected",
            "newer_candidate_awaiting_publish",
        ]
    ]
    content_age_status: Literal[
        "not_applicable", "within_threshold", "warning", "critical", "unknown"
    ]
    freshness_policy_version: str = Field(min_length=1)
    content_age_evidence: ContentAgeEvidence | None

    @model_validator(mode="after")
    def validate_status_invariants(self) -> SourceDataStatus:
        if self.availability == "data_unavailable":
            if (
                self.availability_reason_code is None
                or self.serving_snapshot_id is not None
                or self.serving_curated_build_id is not None
                or self.serving_validation_status != "not_applicable"
                or self.serving_review_status != "not_applicable"
                or self.stale
                or self.stale_reason_codes
            ):
                raise ValueError("unavailable source status must be fail-closed")
        elif self.availability_reason_code is not None:
            raise ValueError("available source status cannot have an availability reason")
        if self.latest_candidate_status == "none" and self.latest_candidate_id is not None:
            raise ValueError("candidate id requires a non-none candidate status")
        if self.latest_candidate_status != "none" and self.latest_candidate_id is None:
            raise ValueError("non-none candidate status requires a candidate id")
        if self.stale != bool(self.stale_reason_codes):
            raise ValueError("stale reason codes must match stale")
        if self.content_age_evidence is not None and self.content_age_status == "not_applicable":
            raise ValueError("content age evidence requires a content age status")
        return self


class DataStatusResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["public-contract-v1"] = "public-contract-v1"
    data_mode: Literal["sample", "official_snapshot"]
    sources: list[SourceDataStatus] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_source_registry(self) -> DataStatusResult:
        expected = {"cdc_manual", "cdc_recognized_labs", "nhi_fee", "tfda_device"}
        source_ids = [source.source_id for source in self.sources]
        if set(source_ids) != expected or len(source_ids) != len(set(source_ids)):
            raise ValueError("data status must contain each contracted source exactly once")
        if self.data_mode == "sample":
            for source in self.sources:
                if (
                    source.availability != "available"
                    or source.serving_snapshot_id is not None
                    or source.serving_curated_build_id is not None
                    or source.serving_validation_status != "not_applicable"
                    or source.serving_review_status != "not_applicable"
                ):
                    raise ValueError("sample data status cannot claim an official serving build")
        return self


class ReservedStatusResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["public-contract-v1"] = "public-contract-v1"
    operation: Literal["standards_status", "eqa_status"]
    configured: Literal[False] = False
    result_status: Literal["data_unavailable"] = "data_unavailable"
    availability_reason_code: Literal["no_serving_snapshot"] = "no_serving_snapshot"
    capabilities: list[str]
    warnings: list[str]
    notes: list[str]
