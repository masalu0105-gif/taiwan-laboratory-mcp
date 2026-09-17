"""Common short names people type, mapped to the wording each dataset actually uses.

Three datasets store names their own way, and none of them stores the way people speak:

  * the roster writes 「國立成功大學醫學院附設醫院」, so a search for 「成大」 matched nothing;
  * a licence's maker column is English, so 「亞培」 found no maker although 1,373 product names
    contain it;
  * a licence names the virus 「新型冠狀病毒」 or 「SARS-CoV-2」, never 「新冠」.

Only the search term is replaced. The answer still shows the dataset's own wording, and the stored
rows are untouched, so these tables are not part of any curated build's fingerprint: they change
what a question finds, never what an answer says.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from ..util import tfda_search_normalize

LAB_ALIAS_RULE = "cdc_lab_alias"
LAB_ALIAS_RULE_VERSION = "cdc-lab-alias-v1"
DEVICE_ALIAS_RULE = "tfda_term_alias"
DEVICE_ALIAS_RULE_VERSION = "tfda-term-alias-v1"
# The one search that reads the licence's maker column; everything else reads names.
MANUFACTURER_FIELDS = ("manufacturer",)


class AliasRulesError(Exception):
    """The packaged rule file is missing or does not say what it must say."""


def _parse_entries(document: Any, version: str, key: str) -> dict[str, str]:
    """Return alias -> query, or raise. A half-read table would silently match nothing."""

    try:
        entries = document["entries" if key == "entries" else key]
        aliases = {entry["alias"]: entry["query"] for entry in entries}
    except (KeyError, TypeError) as exc:
        raise AliasRulesError(f"{version}: {key} is missing or malformed") from exc
    if document.get("rule_version") != version:
        raise AliasRulesError(f"{version}: rule_version does not match")
    if not entries or len(aliases) != len(entries):
        raise AliasRulesError(f"{version}: {key} is empty or lists an alias twice")
    for alias, query in aliases.items():
        if not alias or not query or alias == query:
            raise AliasRulesError(f"{version}: {alias!r} -> {query!r} cannot change a search")
        if alias != tfda_search_normalize(alias) or query != tfda_search_normalize(query):
            raise AliasRulesError(f"{version}: {alias!r} -> {query!r} is not normalized text")
    return aliases


def _document(rule: str) -> Any:
    resource = files("taiwan_lab_mcp").joinpath("rules", rule, "v1.json")
    try:
        return json.loads(resource.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise AliasRulesError(f"{rule}: rule file cannot be read") from exc


@lru_cache(maxsize=1)
def load_lab_aliases() -> dict[str, str]:
    """Short hospital names the roster's own text does not contain."""

    return _parse_entries(_document(LAB_ALIAS_RULE), LAB_ALIAS_RULE_VERSION, "entries")


@lru_cache(maxsize=1)
def load_device_aliases() -> tuple[dict[str, str], dict[str, str]]:
    """Maker names and product words, kept apart because they read different columns."""

    document = _document(DEVICE_ALIAS_RULE)
    return (
        _parse_entries(document, DEVICE_ALIAS_RULE_VERSION, "manufacturer_entries"),
        _parse_entries(document, DEVICE_ALIAS_RULE_VERSION, "product_entries"),
    )


def apply_lab_aliases(words: list[str]) -> list[str]:
    """Replace each word on its own, so 「成大 傷寒」 becomes 「成功大學 傷寒」."""

    aliases = load_lab_aliases()
    return [aliases.get(word, word) for word in words]


def apply_device_alias(query: str, *, fields: tuple[str, ...]) -> str:
    """Replace the whole term, choosing the table by which column the search reads."""

    makers, products = load_device_aliases()
    table = makers if tuple(fields) == MANUFACTURER_FIELDS else products
    return table.get(query, query)
