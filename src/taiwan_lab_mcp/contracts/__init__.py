from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any


@lru_cache(maxsize=1)
def load_public_contract() -> dict[str, Any]:
    return json.loads(
        files("taiwan_lab_mcp")
        .joinpath("contracts", "public-contract-v1.json")
        .read_text(encoding="utf-8")
    )


def operation_spec(name: str) -> dict[str, Any]:
    for operation in load_public_contract()["operations"]:
        if operation["name"] == name:
            return operation
    raise KeyError(name)


@lru_cache(maxsize=3)
def response_schema(name: str) -> dict[str, Any]:
    """Return the packaged response schema after checking the implementation match."""

    from ..models import DataStatusResult, ReservedStatusResult, ToolResult

    model_names = {
        "QueryResultV1": ToolResult,
        "DataStatusResult": DataStatusResult,
        "ReservedStatusResult": ReservedStatusResult,
    }
    try:
        model = model_names[name]
    except KeyError as exc:
        raise KeyError(name) from exc
    declared = load_public_contract()["response_schemas"][name]
    if declared["model"] != f"{model.__module__}.{model.__name__}":
        raise ValueError(f"Contract response model mismatch for {name}")
    schema = declared.get("schema")
    if not isinstance(schema, dict):
        raise ValueError(f"Contract response schema missing for {name}")
    if list(schema.get("properties", {})) != declared["exact_top_level_keys"]:
        raise ValueError(f"Contract response keys mismatch for {name}")
    if schema.get("additionalProperties") != (not declared["closed"]):
        raise ValueError(f"Contract response closure mismatch for {name}")
    if model.model_json_schema() != schema:
        raise ValueError(f"Implementation response schema mismatch for {name}")
    return schema
