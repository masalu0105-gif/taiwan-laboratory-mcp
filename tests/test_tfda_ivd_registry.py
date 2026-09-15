import json
from importlib.resources import files

import pytest

from taiwan_lab_mcp.rules.tfda import (
    ACTIVE_IVD_RULE_VERSION,
    TfdaRuleError,
    classification_codes,
    derive_ivd_scope,
    load_ivd_registry,
    main_category_letters,
    parse_ivd_registry,
)
from taiwan_lab_mcp.util import tfda_search_normalize

ANNEX_SHA256 = "6db4a866a424223ba30aaeeec3794b255a6c1f375764be27ffdeb701cb270e55"


def _registry_bytes():
    return files("taiwan_lab_mcp").joinpath("rules", "tfda_ivd", "v1.json").read_bytes()


def test_packaged_registry_is_the_versioned_ai_review():
    registry = load_ivd_registry()
    assert ACTIVE_IVD_RULE_VERSION == "tfda-ivd-v1"
    assert len(registry) == 551
    assert registry["B.9225"].ivd_scope == "included"
    assert registry["B.9195"].ivd_scope == "excluded"
    assert registry["B.9245"].ivd_scope == "excluded"
    assert all(entry.decision_status == "approved" for entry in registry.values())
    assert {entry.reviewer_id for entry in registry.values()} == {"ai-reviewer:claude-opus-5"}
    assert {entry.source_sha256 for entry in registry.values()} == {ANNEX_SHA256}
    assert {code for code, entry in registry.items() if entry.source_page is None} == {
        "B.2800",
        "B.4010",
        "C.5800",
    }
    annex_entry = registry["A.0001"]
    assert annex_entry.source_page == 2
    assert annex_entry.identification_text_locator == "附表第 2 頁 A.0001 鑑別範圍"
    assert annex_entry.effective_from.isoformat() == "2023-08-22"


def _bundle(**entry_changes):
    document = json.loads(_registry_bytes().decode("utf-8"))
    document["entries"] = [dict(document["entries"][0], **entry_changes)]
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def test_registry_rejects_approved_entry_without_reviewer_evidence():
    with pytest.raises(TfdaRuleError) as error:
        parse_ivd_registry(_bundle(reviewer_id=None))
    assert error.value.code == "IVD_REGISTRY_SCHEMA_INVALID"


def test_registry_rejects_entry_from_another_rule_version():
    with pytest.raises(TfdaRuleError) as error:
        parse_ivd_registry(_bundle(rule_version="tfda-ivd-v0"))
    assert error.value.code == "IVD_REGISTRY_SCHEMA_INVALID"


def test_registry_rejects_duplicate_code():
    document = json.loads(_registry_bytes().decode("utf-8"))
    document["entries"] = [document["entries"][0], document["entries"][0]]
    with pytest.raises(TfdaRuleError) as error:
        parse_ivd_registry(json.dumps(document, ensure_ascii=False).encode("utf-8"))
    assert error.value.code == "DUPLICATE_IVD_CODE"


def test_codes_come_only_from_uppercase_sub_category_codes():
    assert classification_codes(["B.9225 糖化血色素試驗系統", "", "4105 舊制品項"]) == ["B.9225"]
    assert classification_codes(["d.5630 噴霧器"]) == []
    assert classification_codes(["A.1345 甲", "A.1345 甲", "C.3400 乙"]) == ["A.1345", "C.3400"]


def test_main_category_letters_ignore_legacy_numbers():
    assert main_category_letters(["B 血液學及病理學", "A 臨床化學及臨床毒理學", ""]) == ["A", "B"]
    assert main_category_letters(["4000 舊制主類別", "E000"]) == []


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        (["B.9225"], "included"),
        (["B.9225", "Z.0000"], "included"),
        (["B.9225", "B.9195"], "ambiguous"),
        (["B.9195", "B.9245"], "excluded"),
        (["B.9195", "D.1100"], "unknown"),
        (["D.1100"], "unknown"),
        # Owner 2026-09-15: an annex class A/B/C code nobody reviewed yet counts as IVD.
        (["A.5555"], "included"),
        (["C.8888", "B.9195"], "ambiguous"),
        ([], "unknown"),
    ],
)
def test_ivd_scope_join_follows_sdd_rules(codes, expected):
    assert derive_ivd_scope(codes, load_ivd_registry()) == expected


def test_ambiguous_decision_makes_the_row_ambiguous():
    registry = dict(load_ivd_registry())
    registry["C.3400"] = registry["C.3400"].model_copy(update={"ivd_scope": "ambiguous"})
    assert derive_ivd_scope(["C.3400"], registry) == "ambiguous"


def test_tfda_search_normalization_folds_quotes_and_tai():
    assert tfda_search_normalize("“星歐” 拋棄式") == tfda_search_normalize('"星歐" 拋棄式')
    assert tfda_search_normalize("〝眼力健〞") == '"眼力健"'
    assert tfda_search_normalize("臺灣") == "台灣"
    assert tfda_search_normalize("  ＡＢＣ－１２３  ") == "abc-123"
