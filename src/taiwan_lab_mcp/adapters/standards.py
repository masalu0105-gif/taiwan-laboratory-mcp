from __future__ import annotations

from typing import Protocol

from ..models import DataRecord


class StandardsAdapter(Protocol):
    """Interface only: a licensed provider must supply terminology or profiles."""

    def search(self, query: str) -> list[DataRecord]: ...

    def get_record(self, identifier: str) -> DataRecord | None: ...


def standards_status() -> dict[str, str]:
    return {
        "loinc": "adapter reserved; Taiwan mapping not implemented",
        "fhir": "adapter reserved; no profile validation implemented",
        "snomed_ct": "adapter reserved; licensing/integration required",
    }
