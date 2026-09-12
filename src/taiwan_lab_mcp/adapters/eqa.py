from __future__ import annotations

from typing import Protocol

from ..models import DataRecord


class EQAAdapter(Protocol):
    """TODO: confirm provider licensing before implementing any catalog access."""

    def search_programs(self, analyte: str, year: int) -> list[DataRecord]: ...


def eqa_status() -> dict:
    return {
        "status": "not_configured",
        "catalog_access_enabled": False,
        "note": "EQA/CAP adapter reserved; catalog retrieval requires confirmed provider permission.",
    }
