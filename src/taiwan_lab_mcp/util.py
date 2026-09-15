from __future__ import annotations

import re
import unicodedata


def norm(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower().strip()
    return re.sub(r"[\s\-_/、,，()（）]+", "", text)


def search_normalize(text: str | None) -> str:
    """Public search normalization: preserve punctuation, collapse whitespace."""

    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", text).casefold().strip()
    return re.sub(r"\s+", " ", text)


# NFKC keeps curly and CJK quotation marks and 臺/台 distinct (checked 2026-09-15); TFDA
# brand names use all of them, so search columns fold them while raw values stay unchanged.
_TFDA_SEARCH_FOLD = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "〝": '"',
        "〞": '"',
        "〟": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "臺": "台",
    }
)


def tfda_search_normalize(text: str | None) -> str:
    """TFDA search normalization: search_normalize plus quote and 臺→台 folding."""

    return search_normalize(text).translate(_TFDA_SEARCH_FOLD)


def checked_query(query: str) -> str:
    if not isinstance(query, str) or len(query) > 200 or not norm(query):
        raise ValueError("Query must contain searchable text and be at most 200 characters")
    return norm(query)


def contains_any(record: dict, query: str, fields: list[str]) -> bool:
    nq = checked_query(query)
    return any(nq in norm(str(record.get(field, ""))) for field in fields)
