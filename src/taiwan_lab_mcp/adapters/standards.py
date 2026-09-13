from __future__ import annotations

from typing import Protocol

from ..models import DataRecord, ReservedStatusResult


class StandardsAdapter(Protocol):
    """Interface only: a licensed provider must supply terminology or profiles."""

    def search(self, query: str) -> list[DataRecord]: ...

    def get_record(self, identifier: str) -> DataRecord | None: ...


def standards_status() -> ReservedStatusResult:
    return ReservedStatusResult(
        operation="standards_status",
        capabilities=["LOINC", "FHIR", "SNOMED"],
        warnings=["reserved_capability_unconfigured"],
        notes=["LOINC/FHIR/SNOMED 僅保留介面，未設定資料或授權；不提供術語 catalog。"],
    )
