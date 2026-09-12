from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictBool,
    computed_field,
    model_validator,
)


class Provenance(BaseModel):
    """Origin of a record; unknown publisher dates remain explicitly unknown."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_name: str = Field(min_length=1)
    source_url: HttpUrl
    version: str = Field(min_length=1)
    updated_at: date | None
    updated_at_note: str | None = None
    method: Literal["synthetic", "manual_review", "structured_import"]
    locator: str = Field(min_length=1)
    retrieved_at: datetime | None = None
    license: str | None = None
    license_url: HttpUrl | None = None

    @model_validator(mode="after")
    def validate_origin(self) -> Provenance:
        if self.updated_at is None and not (self.updated_at_note or "").strip():
            raise ValueError("Unknown updated_at requires an explanation")
        if self.retrieved_at is not None and self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return self


class DataRecord(BaseModel):
    """Shared metadata contract; domain fields are preserved without rewriting."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    source_url: HttpUrl
    version: str = Field(min_length=1)
    updated_at: date | None
    sample_only: StrictBool
    provenance: Provenance

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


class ToolResult(BaseModel):
    query: str
    status: Literal["ok", "not_found", "sample_only"]
    data_mode: Literal["sample"] = "sample"
    sample_only: Literal[True] = True
    items: list[dict] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def count(self) -> int:
        return len(self.items)
