"""Versioned TFDA IVD classification registry and the SDD 10.2 row join."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from importlib.resources import files
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ACTIVE_IVD_RULE_VERSION = "tfda-ivd-v1"
ACTIVE_IVD_RULE_FILE = "v1.json"
IvdScope = Literal["included", "excluded", "ambiguous", "unknown"]
# The reviewed annex covers classes A, B and C. Owner 2026-09-15: a code of these classes
# without a decision yet counts as included ("先當成「算」").
UNREVIEWED_ANNEX_CODE_SCOPE = {"A": "included", "B": "included", "C": "included"}

# Only an uppercase A–P letter, a dot and four digits at the start of 醫器次類別 is a code;
# legacy numeric classes and values such as "d.5630" stay without a code (owner 2026-09-14).
_CODE_RE = re.compile(r"^([A-P])\.([0-9]{4})(?![0-9])")
_MAIN_LETTER_RE = re.compile(r"^([A-P])(?![A-Za-z0-9])")


class TfdaRuleError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}{(': ' + detail) if detail else ''}")


class IvdDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification_code: str = Field(pattern=r"^[A-P]\.[0-9]{4}$")
    zh_name_raw: str = Field(min_length=1)
    en_name_raw: str | None
    risk_class_raw: str | None
    identification_text_locator: str = Field(min_length=1)
    regulation_version: str | None
    effective_from: date | None
    source_url: str = Field(min_length=1)
    source_page: Annotated[int, Field(ge=1)] | None
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ivd_scope: Literal["included", "excluded", "ambiguous"]
    decision_basis: str = Field(min_length=1)
    reviewer_id: str | None
    reviewed_at: datetime | None
    rule_version: Literal["tfda-ivd-v1"]
    decision_status: Literal["approved", "review_pending", "rejected"]

    @model_validator(mode="after")
    def validate_evidence(self) -> IvdDecision:
        if self.decision_status == "approved" and (
            not self.reviewer_id or self.reviewed_at is None
        ):
            raise ValueError("approved IVD decision requires reviewer evidence")
        if self.reviewed_at is not None and self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        # A code missing from the annex has no page, regulation version or effective date.
        annex_fields = (self.source_page, self.regulation_version, self.effective_from)
        if any(value is None for value in annex_fields) and any(
            value is not None for value in annex_fields
        ):
            raise ValueError("annex page, regulation version and effective date go together")
        return self


class IvdRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_version: Literal["tfda-ivd-v1"]
    source_id: Literal["tfda_devices"]
    status: Literal["complete", "review_incomplete"]
    reviewer_note: str = Field(min_length=1)
    review_record: str = Field(min_length=1)
    decisions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: list[IvdDecision]

    @model_validator(mode="after")
    def validate_entry_versions(self) -> IvdRegistry:
        if any(entry.rule_version != self.rule_version for entry in self.entries):
            raise ValueError("every IVD decision must use the registry rule_version")
        return self


def parse_ivd_registry(payload: bytes) -> dict[str, IvdDecision]:
    """Return approved decisions by classification code."""

    try:
        registry = IvdRegistry.model_validate(json.loads(payload.decode("utf-8")))
    except (UnicodeDecodeError, ValueError) as exc:
        raise TfdaRuleError("IVD_REGISTRY_SCHEMA_INVALID", str(exc)) from exc
    decisions: dict[str, IvdDecision] = {}
    seen: set[str] = set()
    for entry in registry.entries:
        if entry.classification_code in seen:
            raise TfdaRuleError("DUPLICATE_IVD_CODE", entry.classification_code)
        seen.add(entry.classification_code)
        if entry.decision_status == "approved":
            decisions[entry.classification_code] = entry
    return decisions


def packaged_ivd_registry_bytes() -> bytes:
    return files("taiwan_lab_mcp").joinpath("rules", "tfda_ivd", ACTIVE_IVD_RULE_FILE).read_bytes()


def load_ivd_registry() -> dict[str, IvdDecision]:
    return parse_ivd_registry(packaged_ivd_registry_bytes())


def classification_codes(sub_category_values: Iterable[str]) -> list[str]:
    codes: list[str] = []
    for value in sub_category_values:
        match = _CODE_RE.match((value or "").strip())
        if match is not None:
            code = f"{match.group(1)}.{match.group(2)}"
            if code not in codes:
                codes.append(code)
    return codes


def main_category_letters(main_category_values: Iterable[str]) -> list[str]:
    letters = {
        match.group(1)
        for value in main_category_values
        if (match := _MAIN_LETTER_RE.match((value or "").strip())) is not None
    }
    return sorted(letters)


def derive_ivd_scope(codes: Iterable[str], decisions: Mapping[str, IvdDecision]) -> IvdScope:
    """SDD 10.2 join: codes from 醫器次類別 only; keywords never change the result.

    Owner 2026-09-15: an annex class A/B/C code without a decision yet counts as included
    until it is reviewed; codes of other classes stay unreviewed.
    """

    scopes = [
        decisions[code].ivd_scope if code in decisions else UNREVIEWED_ANNEX_CODE_SCOPE.get(code[0])
        for code in codes
    ]
    if not scopes:
        return "unknown"
    if "ambiguous" in scopes:
        return "ambiguous"
    if "included" in scopes:
        return "ambiguous" if "excluded" in scopes else "included"
    if all(scope == "excluded" for scope in scopes):
        return "excluded"
    return "unknown"


_CANCELLED_STATUSES = frozenset({"已註銷", "已廢止"})


@dataclass(frozen=True)
class TemporalEvaluation:
    cancellation_recorded_in_source: bool | str
    within_validity_period_as_of: bool | str
    warnings: list[str]


def cancellation_consistency(
    status_raw: str | None, cancellation_date: date | None
) -> tuple[bool | str, list[str]]:
    """PRD 6.3.1 first table: the status is trimmed, and blank never means 未註銷."""

    status = (status_raw or "").strip()
    if status == "":
        return (True, ["cancellation_date_without_status"]) if cancellation_date else (False, [])
    if status in _CANCELLED_STATUSES:
        return True, ([] if cancellation_date else ["cancellation_status_without_date"])
    return "unknown", ["unknown_cancellation_status"]


def evaluate_temporal(
    status_raw: str | None,
    cancellation_date: date | None,
    valid_through: date | None,
    as_of: date,
) -> TemporalEvaluation:
    """PRD 6.3.1 at query time; the two outputs are never merged into one validity state."""

    recorded, warnings = cancellation_consistency(status_raw, cancellation_date)
    validity: bool | str = "unknown" if valid_through is None else as_of <= valid_through
    if recorded == "unknown":
        warnings.append("cancellation_record_ambiguous")
        if validity is False:
            warnings.append("validity_period_elapsed")
    if validity == "unknown":
        warnings.append("validity_date_unavailable")
    elif recorded is True:
        warnings.append(
            "cancellation_recorded_within_validity_window"
            if validity
            else "cancellation_recorded_and_validity_period_elapsed"
        )
    elif recorded is False and validity is False:
        warnings.append("validity_period_elapsed")
    return TemporalEvaluation(recorded, validity, warnings)
