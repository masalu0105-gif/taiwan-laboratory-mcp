from __future__ import annotations

from typing import Protocol

from ..models import DataRecord, ReservedStatusResult


class EQAAdapter(Protocol):
    """TODO: confirm provider licensing before implementing any catalog access."""

    def search_programs(self, analyte: str, year: int) -> list[DataRecord]: ...


def eqa_status() -> ReservedStatusResult:
    return ReservedStatusResult(
        operation="eqa_status",
        capabilities=["EQA", "CAP"],
        warnings=["reserved_capability_unconfigured"],
        notes=["EQA/CAP 僅保留介面，未設定資料或授權；不提供 catalog。"],
    )
