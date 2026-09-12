from __future__ import annotations

from ..models import ToolResult
from ..sources import NHI_FEE
from ..util import checked_query, contains_any, norm
from .base import load_sample, sample_result


class NHIAdapter:
    def __init__(self) -> None:
        self.fees = load_sample("nhi_fee.sample.json")

    def search_lab_code(self, query: str) -> ToolResult:
        checked_query(query)
        fields = ["code", "name_zh", "name_en", "note"]
        rows = [r for r in self.fees if contains_any(r, query, fields)]
        return sample_result(query, rows, NHI_FEE)

    def get_points(self, code: str) -> ToolResult:
        nc = checked_query(code)
        rows = [r for r in self.fees if norm(r.get("code")) == nc]
        result = sample_result(code, rows, NHI_FEE)
        result.notes.append("支付點數的單位為點；未提供點數時保留 null，不換算為新臺幣。")
        return result

    def get_payment_rule(self, query: str) -> ToolResult:
        return self.search_lab_code(query)
