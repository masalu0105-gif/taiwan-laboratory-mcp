from __future__ import annotations

import json
from datetime import datetime
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..util import search_normalize


class NhiRuleError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}{(': ' + detail) if detail else ''}")


class ScopeRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    scope_status: Literal["in_scope", "out_of_scope", "review_pending"]
    basis_type: str = Field(min_length=1)
    basis_url: str = Field(min_length=1)
    basis_locator: str = Field(min_length=1)
    rule_version: Literal["nhi-lab-scope-v1"]
    reviewer_id: str | None
    reviewed_at: datetime | None
    decision_status: Literal["approved", "review_pending", "rejected"]

    @model_validator(mode="after")
    def validate_approval_evidence(self) -> ScopeRule:
        if self.decision_status == "approved" and (
            self.scope_status == "review_pending"
            or not self.reviewer_id
            or self.reviewed_at is None
        ):
            raise ValueError("approved scope rule requires a resolved status and reviewer evidence")
        if self.reviewed_at is not None and self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        return self


class ScopeBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_version: Literal["nhi-lab-scope-v1"]
    source_id: Literal["nhi_fee"]
    status: Literal["complete", "review_incomplete"]
    entries: list[ScopeRule]
    note: str | None = None


class AliasRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias_raw: str = Field(min_length=1)
    code: str = Field(min_length=1)
    language: str = Field(min_length=1)
    basis_type: str = Field(min_length=1)
    basis_url: str = Field(min_length=1)
    basis_locator: str = Field(min_length=1)
    rule_version: Literal["nhi-aliases-v1"]
    reviewer_id: str | None
    reviewed_at: datetime | None
    decision_status: Literal["approved", "review_pending", "rejected"]
    collision_disposition: Literal["return_all", "not_applicable", "blocked"]

    @model_validator(mode="after")
    def validate_approval_evidence(self) -> AliasRule:
        if self.decision_status == "approved" and (
            not self.reviewer_id
            or self.reviewed_at is None
            or self.collision_disposition != "return_all"
        ):
            raise ValueError(
                "approved alias requires reviewer evidence and return_all collision handling"
            )
        if self.reviewed_at is not None and self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        return self


class AliasBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_version: Literal["nhi-aliases-v1"]
    source_id: Literal["nhi_fee"]
    entries: list[AliasRule]


def _decode(payload: bytes) -> dict:
    if not isinstance(payload, bytes) or not payload:
        raise NhiRuleError("EMPTY_RULE_BUNDLE")
    try:
        value = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NhiRuleError("RULE_BUNDLE_DECODE_ERROR") from exc
    if not isinstance(value, dict):
        raise NhiRuleError("RULE_BUNDLE_NOT_OBJECT")
    return value


def parse_scope_bundle(payload: bytes) -> dict[str, ScopeRule]:
    try:
        bundle = ScopeBundle.model_validate(_decode(payload))
    except NhiRuleError:
        raise
    except ValueError as exc:
        raise NhiRuleError("SCOPE_SCHEMA_INVALID", str(exc)) from exc
    rules: dict[str, ScopeRule] = {}
    seen_codes: set[str] = set()
    for entry in bundle.entries:
        key = entry.code.strip()
        normalized_key = search_normalize(key)
        if normalized_key in seen_codes:
            raise NhiRuleError("DUPLICATE_SCOPE_CODE", entry.code)
        seen_codes.add(normalized_key)
        if entry.decision_status == "approved":
            rules[key] = entry
    return rules


def parse_alias_bundle(payload: bytes) -> dict[str, tuple[str, ...]]:
    try:
        bundle = AliasBundle.model_validate(_decode(payload))
    except NhiRuleError:
        raise
    except ValueError as exc:
        raise NhiRuleError("ALIAS_SCHEMA_INVALID", str(exc)) from exc
    aliases: dict[str, set[str]] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for entry in bundle.entries:
        if entry.decision_status != "approved":
            continue
        key = search_normalize(entry.alias_raw)
        pair = (key, search_normalize(entry.code))
        if pair in seen_pairs:
            raise NhiRuleError("DUPLICATE_ALIAS_CODE", entry.alias_raw)
        seen_pairs.add(pair)
        aliases.setdefault(key, set()).add(entry.code.strip())
    return {key: tuple(sorted(codes)) for key, codes in aliases.items()}


def load_scope_rules() -> dict[str, ScopeRule]:
    payload = files("taiwan_lab_mcp").joinpath("rules", "nhi_lab_scope", "v1.json").read_bytes()
    return parse_scope_bundle(payload)


def load_aliases() -> dict[str, tuple[str, ...]]:
    payload = files("taiwan_lab_mcp").joinpath("rules", "nhi_aliases", "v1.json").read_bytes()
    return parse_alias_bundle(payload)
