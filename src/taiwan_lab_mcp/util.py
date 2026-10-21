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


def edit_distance(a: str, b: str, limit: int = 2) -> int:
    """Optimal string alignment distance (insert, delete, substitute, swap two neighbours).

    Returns limit + 1 as soon as the distance is known to exceed limit, so callers can use it
    on short identifiers and words without paying for long strings.
    """

    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] | None = None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1] if prev[-1] <= limit else limit + 1


def typo_limit(word: str) -> int:
    """How many typos a word of this length may carry and still count as that word."""

    if len(word) < 5:
        return 0
    return 1 if len(word) < 8 else 2
