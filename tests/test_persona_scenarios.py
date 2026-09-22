from __future__ import annotations

import json
from pathlib import Path

from taiwan_lab_mcp.contracts import load_public_contract

MATRIX = Path(__file__).parent / "scenarios" / "persona-scenarios-v1.json"


def test_persona_matrix_is_exactly_ten_by_ten_and_uses_public_tools() -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    public_tools = {operation["name"] for operation in load_public_contract()["operations"]}

    assert matrix["version"] == "persona-scenarios-v1"
    assert len(matrix["personas"]) == 10
    assert all(len(persona["questions"]) == 10 for persona in matrix["personas"])

    persona_ids = [persona["id"] for persona in matrix["personas"]]
    case_ids = [case["id"] for persona in matrix["personas"] for case in persona["questions"]]
    assert len(set(persona_ids)) == 10
    assert len(case_ids) == len(set(case_ids)) == 100
    assert all(case["tool"] in public_tools for p in matrix["personas"] for case in p["questions"])


def test_persona_matrix_has_explicit_safe_expectations_and_no_patient_examples() -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    forbidden = ("病人姓名", "身分證", "病歷號", "電話號碼", "住址")
    for persona in matrix["personas"]:
        for case in persona["questions"]:
            assert case["question"].strip()
            assert isinstance(case["arguments"], dict)
            assert case["expect"].get("status") or case["expect"].get("statuses")
            assert not any(word in case["question"] for word in forbidden)
