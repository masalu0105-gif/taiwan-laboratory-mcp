from __future__ import annotations

from ..models import ToolResult
from ..sources import CDC_LABS, CDC_SPECIMEN
from ..util import checked_query, contains_any, norm
from .base import load_sample, sample_result


class CDCAdapter:
    def __init__(self) -> None:
        self.specimens = load_sample("cdc_specimen.sample.json")
        self.labs = load_sample("cdc_labs.sample.json")

    def search_disease(self, query: str) -> ToolResult:
        nq = checked_query(query)
        rows = [
            row
            for row in self.specimens
            if any(nq in norm(x) for x in [row["disease"], *row.get("aliases", [])])
        ]
        return sample_result(query, rows, CDC_SPECIMEN)

    def get_specimen_requirement(self, disease: str) -> ToolResult:
        return self.search_disease(disease)

    def find_authorized_lab(self, query: str, city: str | None = None) -> ToolResult:
        checked_query(query)
        rows = [r for r in self.labs if contains_any(r, query, ["name", "scope"])]
        if city is not None:
            nc = checked_query(city)
            rows = [r for r in rows if nc in norm(r.get("city"))]
        return sample_result(query, rows, CDC_LABS)
