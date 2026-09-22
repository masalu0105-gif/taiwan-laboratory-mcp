"""Common short names people actually type, mapped to the wording each dataset uses."""

import pytest


def test_the_roster_table_only_maps_names_the_roster_does_not_already_match() -> None:
    """An alias whose own text already appears in the data would only narrow the answer."""

    from taiwan_lab_mcp.rules.aliases import load_lab_aliases

    aliases = load_lab_aliases()
    assert aliases
    for alias, target in aliases.items():
        assert alias != target
        assert alias not in target


def test_the_roster_table_is_keyed_on_the_normalized_text() -> None:
    """臺 folds to 台 in the search column, so both spellings must be the same key."""

    from taiwan_lab_mcp.rules.aliases import load_lab_aliases
    from taiwan_lab_mcp.util import tfda_search_normalize

    for alias, target in load_lab_aliases().items():
        assert alias == tfda_search_normalize(alias)
        assert target == tfda_search_normalize(target)


def test_a_short_hospital_name_is_replaced_word_by_word() -> None:
    """「成大 傷寒」 has to become 「成功大學 傷寒」, not be looked up as one lump."""

    from taiwan_lab_mcp.rules.aliases import apply_lab_aliases

    assert apply_lab_aliases(["成大"]) == ["成功大學"]
    assert apply_lab_aliases(["成大", "傷寒"]) == ["成功大學", "傷寒"]
    assert apply_lab_aliases(["傷寒"]) == ["傷寒"]


def test_the_device_table_keeps_maker_names_apart_from_product_words() -> None:
    """The maker column is English and the product column is Chinese; one map cannot serve both."""

    from taiwan_lab_mcp.rules.aliases import load_device_aliases

    makers, products = load_device_aliases()
    assert makers and products
    assert makers["亞培"] == "abbott"
    assert "亞培" not in products


def test_looking_for_a_maker_by_its_chinese_name_asks_for_the_english_one() -> None:
    from taiwan_lab_mcp.rules.aliases import apply_device_alias

    assert apply_device_alias("亞培", fields=("manufacturer",)) == "abbott"
    # The same word typed into a product search must not be rewritten: 「亞培」 is in the
    # Chinese product names, and 「Abbott」 is not.
    assert apply_device_alias("亞培", fields=("name_zh", "name_en")) == "亞培"


def test_a_covid_question_asks_for_wording_the_licences_actually_use() -> None:
    from taiwan_lab_mcp.rules.aliases import apply_device_alias, apply_device_aliases

    assert apply_device_alias("新冠", fields=("name_zh", "name_en")) != "新冠"
    assert apply_device_aliases("新冠", fields=("name_zh", "name_en")) == (
        "新型冠狀病毒",
        "sars-cov-2",
        "covid-19",
    )
    assert (
        apply_device_alias("嚴重特殊傳染性肺炎", fields=("name_zh", "name_en"))
        != "嚴重特殊傳染性肺炎"
    )


def test_a_broken_rule_file_stops_the_query_rather_than_quietly_matching_nothing() -> None:
    from taiwan_lab_mcp.rules.aliases import AliasRulesError, _parse_entries, _parse_multi_entries

    with pytest.raises(AliasRulesError):
        _parse_entries({"rule_version": "wrong", "entries": []}, "cdc-lab-alias-v1", "entries")
    with pytest.raises(AliasRulesError):
        _parse_entries(
            {"rule_version": "cdc-lab-alias-v1", "entries": [{"alias": "a"}]},
            "cdc-lab-alias-v1",
            "entries",
        )
    with pytest.raises(AliasRulesError):
        # A union rule may not silently collapse repeated variants.
        _parse_multi_entries(
            {
                "rule_version": "tfda-term-alias-v2",
                "product_entries": [{"alias": "新冠", "queries": ["新型冠狀病毒", "新型冠狀病毒"]}],
            },
            "tfda-term-alias-v2",
            "product_entries",
        )
    with pytest.raises(AliasRulesError):
        # Every union member must already use the same normalization as the index.
        _parse_multi_entries(
            {
                "rule_version": "tfda-term-alias-v2",
                "product_entries": [{"alias": "新冠", "queries": ["COVID-19"]}],
            },
            "tfda-term-alias-v2",
            "product_entries",
        )
    with pytest.raises(AliasRulesError):
        # The same alias twice would silently drop one of them.
        _parse_entries(
            {
                "rule_version": "cdc-lab-alias-v1",
                "entries": [
                    {"alias": "成大", "query": "成功大學"},
                    {"alias": "成大", "query": "x"},
                ],
            },
            "cdc-lab-alias-v1",
            "entries",
        )
