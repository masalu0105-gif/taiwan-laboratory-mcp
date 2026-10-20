"""Accept the argument names people and models actually send.

The published schema stays exact. Callers still say `query` or `license_no`, but a call that
uses the neighbouring tool's name (`disease` on search_disease, `licence_no` on get_license)
is rewritten before validation. Anything that still does not fit raises a short error instead
of a schema dump that the usage log then records as an ordinary HTTP 200.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .contracts import operation_spec

# Extra names for a canonical parameter. Only used when that parameter was not sent.
_ALIASES: dict[str, tuple[str, ...]] = {
    "query": (
        "q",
        "keyword",
        "keywords",
        "search",
        "term",
        "text",
        "disease",
        "disease_name",
        "code",
        "name",
    ),
    "disease": ("query", "q", "keyword", "keywords", "search", "term", "disease_name"),
    "license_no": (
        "license",
        "licence",
        "license_number",
        "license_id",
        "permit",
        "permit_no",
    ),
    "code": ("query", "q", "keyword", "payment_code", "nhi_code"),
    "name": ("query", "q", "manufacturer", "maker", "manufacturer_name"),
    "city": ("county", "city_name"),
    "manufacturer": ("maker", "manufacturer_name", "vendor"),
    "as_of": ("as_of_date", "date"),
    "limit": ("page_size", "count"),
    "offset": ("skip",),
}


class ArgumentCoercionError(Exception):
    """The call named parameters this tool does not take, and none is an obvious alias."""


def _snake(key: str) -> str:
    step = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    step = step.replace("-", "_").replace(" ", "_").lower()
    return step.replace("licence", "license")


def _blank_to_none(value: Any, *, nullable: bool) -> Any:
    if nullable and isinstance(value, str) and not value.strip():
        return None
    return value


def _fold_closed_string(name: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if name == "ivd_scope":
        return value.strip().lower()
    if name in {"main_category", "prefer_main_category"}:
        return value.strip().upper()
    return value


def coerce_tool_arguments(tool_name: str, arguments: Any) -> Any:
    """Return arguments under the published names, or raise ArgumentCoercionError."""

    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            arguments = parsed
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ArgumentCoercionError(
            f"{tool_name} 的參數必須是物件，收到的是 {type(arguments).__name__}。"
        )
    try:
        spec = operation_spec(tool_name)
    except KeyError:
        return arguments

    parameters = spec["parameters"]
    by_name = {parameter["name"]: parameter for parameter in parameters}
    assigned: dict[str, Any] = {}
    leftovers: dict[str, Any] = {}
    for raw_key, value in arguments.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ArgumentCoercionError(f"{tool_name} 的參數名稱必須是非空字串。")
        key = _snake(raw_key)
        target = assigned if key in by_name else leftovers
        current = target.get(key, _MISSING)
        if current is not _MISSING and current != value:
            raise ArgumentCoercionError(f"{tool_name} 的參數 {key} 收到兩個不同的值（{raw_key}）。")
        target[key] = value

    for parameter in parameters:
        name = parameter["name"]
        choices = [alias for alias in _ALIASES.get(name, ()) if alias in leftovers]
        if name in assigned:
            disagree = [alias for alias in choices if leftovers[alias] != assigned[name]]
            if disagree:
                joined = "、".join(disagree)
                raise ArgumentCoercionError(
                    f"{tool_name} 的參數 {name} 與 {joined} 內容不同，無法判斷要用哪一個。"
                )
            for alias in choices:
                leftovers.pop(alias, None)
            continue
        values = {leftovers[alias] for alias in choices}
        if len(values) > 1:
            raise ArgumentCoercionError(
                f"{tool_name} 的參數 {name} 有多個寫法且內容不同：{'、'.join(choices)}。"
            )
        if choices:
            assigned[name] = leftovers.pop(choices[0])
            for alias in choices[1:]:
                leftovers.pop(alias, None)

    missing = [
        parameter["name"]
        for parameter in parameters
        if parameter["required"] and parameter["name"] not in assigned
    ]
    if missing:
        received = ", ".join(str(key) for key in arguments) or "（沒有參數）"
        accepted = []
        for name in missing:
            aliases = [alias for alias in _ALIASES.get(name, ()) if alias not in by_name]
            extra = f"（也接受 {'、'.join(aliases)}）" if aliases else ""
            accepted.append(f"{name}{extra}")
        raise ArgumentCoercionError(
            f"{tool_name} 缺少參數 {'、'.join(accepted)}。這次收到的是：{received}。"
        )

    coerced: dict[str, Any] = {}
    for name, value in assigned.items():
        parameter = by_name[name]
        value = _blank_to_none(value, nullable=bool(parameter["nullable"]))
        coerced[name] = _fold_closed_string(name, value)
    return coerced


_MISSING = object()
