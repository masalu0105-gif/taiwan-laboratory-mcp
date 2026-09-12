from __future__ import annotations

import re
import unicodedata


def norm(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower().strip()
    return re.sub(r"[\s\-_/、,，()（）]+", "", text)


def checked_query(query: str) -> str:
    if not isinstance(query, str) or len(query) > 200 or not norm(query):
        raise ValueError("Query must contain searchable text and be at most 200 characters")
    return norm(query)


def contains_any(record: dict, query: str, fields: list[str]) -> bool:
    nq = checked_query(query)
    return any(nq in norm(str(record.get(field, ""))) for field in fields)
