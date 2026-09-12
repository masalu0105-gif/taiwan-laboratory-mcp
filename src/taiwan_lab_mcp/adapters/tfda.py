from __future__ import annotations

from ..models import ToolResult
from ..sources import TFDA_DEVICE
from ..util import checked_query, contains_any, norm
from .base import load_sample, sample_result


class TFDAAdapter:
    def __init__(self) -> None:
        self.devices = load_sample("tfda_devices.sample.json")

    def search_ivd(self, query: str, manufacturer: str | None = None) -> ToolResult:
        checked_query(query)
        fields = ["license_no", "name_zh", "name_en", "effect", "manufacturer", "applicant"]
        rows = [r for r in self.devices if contains_any(r, query, fields)]
        if manufacturer is not None:
            nm = checked_query(manufacturer)
            rows = [r for r in rows if nm in norm(r.get("manufacturer"))]
        return sample_result(query, rows, TFDA_DEVICE)

    def get_license(self, license_no: str) -> ToolResult:
        nl = checked_query(license_no)
        rows = [r for r in self.devices if norm(r.get("license_no")) == nl]
        return sample_result(license_no, rows, TFDA_DEVICE)

    def find_manufacturer(self, name: str) -> ToolResult:
        return self.search_ivd(name, manufacturer=name)

    def compare_products(self, query: str, limit: int = 10) -> ToolResult:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("limit must be an integer between 1 and 50")
        result = self.search_ivd(query)
        total = result.count
        result.items = result.items[:limit]
        result.notes.append(
            f"回傳 {result.count} / {total} 筆示範結果；不代表產品可互換或臨床等效。"
        )
        return result
