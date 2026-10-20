"""English and Chinese words for the same disease or analyte.

The packaged tables change which rows a question finds. They do not change the text of an
answer: callers still return the dataset's own disease name, fee name or licence fields.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from ..util import norm, tfda_search_normalize

SYNONYM_RULE = "search_synonyms"
SYNONYM_RULE_VERSION = "search-synonyms-v1"


class SynonymRulesError(Exception):
    """The packaged synonym file is missing or lists the same word twice."""


def _document() -> Any:
    resource = files("taiwan_lab_mcp").joinpath("rules", SYNONYM_RULE, "v1.json")
    try:
        return json.loads(resource.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SynonymRulesError("search synonyms cannot be read") from exc


@lru_cache(maxsize=1)
def _indexes() -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    document = _document()
    if document.get("rule_version") != SYNONYM_RULE_VERSION:
        raise SynonymRulesError("search-synonyms-v1: rule_version does not match")
    diseases: dict[str, str] = {}
    try:
        disease_entries = document["diseases"]
        analyte_entries = document["analytes"]
    except (KeyError, TypeError) as exc:
        raise SynonymRulesError("search synonyms are missing diseases or analytes") from exc
    if not isinstance(disease_entries, list) or not disease_entries:
        raise SynonymRulesError("search synonyms list no diseases")
    if not isinstance(analyte_entries, list) or not analyte_entries:
        raise SynonymRulesError("search synonyms list no analytes")
    for entry in disease_entries:
        try:
            canonical = norm(entry["canonical"])
            aliases = [norm(alias) for alias in entry["aliases"]]
        except (KeyError, TypeError) as exc:
            raise SynonymRulesError("a disease synonym entry is malformed") from exc
        if not canonical or not aliases:
            raise SynonymRulesError("a disease synonym entry is empty")
        for alias in aliases:
            if not alias or alias == canonical or alias in diseases:
                raise SynonymRulesError(f"{alias!r} cannot be a disease synonym")
            diseases[alias] = canonical
    analytes: dict[str, tuple[str, ...]] = {}
    for entry in analyte_entries:
        try:
            terms = [tfda_search_normalize(term) for term in entry["terms"]]
        except (KeyError, TypeError) as exc:
            raise SynonymRulesError("an analyte synonym entry is malformed") from exc
        variants = tuple(dict.fromkeys(terms))
        if len(variants) < 2 or any(not term for term in variants):
            raise SynonymRulesError("an analyte synonym group needs two different terms")
        for term in variants:
            if term in analytes:
                raise SynonymRulesError(f"{term!r} is in two analyte groups")
            analytes[term] = variants
    return diseases, analytes


def resolve_disease_query(text: str) -> str | None:
    """Manual or roster wording for a disease alias, or None when the text is not one.

    The specimen-manual table is consulted first: those targets were checked against the
    manual. This file then fills phrases that table does not list, such as 「dengue fever」.
    """

    key = norm(text)
    if not key:
        return None
    from ..importers.cdc_manual import load_cdc_disease_aliases

    mapped = load_cdc_disease_aliases().get(key)
    if mapped:
        return mapped
    return _indexes()[0].get(key)


def disease_words(query: str) -> list[str]:
    """Words to search, after a whole-phrase disease alias or a word-by-word one.

    「dengue fever」 is one disease, so it is not split into 「dengue」 and 「fever」.
    「台北 dengue」 is not one disease: dengue is rewritten and 台北 stays a city word.
    """

    from .aliases import apply_lab_aliases

    normalized = tfda_search_normalize(query)
    if not normalized:
        return []
    mapped = resolve_disease_query(normalized)
    if mapped:
        return [tfda_search_normalize(mapped)]
    words = apply_lab_aliases([word for word in normalized.split(" ") if word])
    rewritten: list[str] = []
    for word in words:
        mapped_word = resolve_disease_query(word)
        rewritten.append(tfda_search_normalize(mapped_word) if mapped_word else word)
    return rewritten


def disease_search_text(text: str) -> str:
    """Same rewrite for sample fixtures, which match one string rather than SQL words."""

    mapped = resolve_disease_query(text)
    if mapped:
        return mapped
    normalized = tfda_search_normalize(text)
    parts: list[str] = []
    changed = False
    for word in normalized.split(" "):
        mapped_word = resolve_disease_query(word)
        if mapped_word:
            parts.append(mapped_word)
            changed = True
        else:
            parts.append(word)
    if changed:
        return " ".join(parts)
    return text


def analyte_needles(text: str) -> tuple[str, ...]:
    """Every spelling of this analyte, or the text itself when it is not in a group."""

    key = tfda_search_normalize(text)
    if not key:
        return ()
    group = _indexes()[1].get(key)
    if group:
        return group
    return (key,)
