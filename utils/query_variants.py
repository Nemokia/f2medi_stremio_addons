"""Deterministic WordPress search query variants (movie discovery fix).

Cinemeta titles carry punctuation ("Avengers: Endgame") that the site's
WP search engine fails to match against post titles stored without it
("Avengers Endgame 2019"). This module produces a small, ordered,
de-duplicated list of search queries built on top of
:mod:`utils.normalization` — no parallel normalization logic lives here.

Variant order (deterministic):

1. the original title, whitespace-collapsed;
2. the punctuation-stripped title (colons, dashes, quotes ... become
   spaces) — only added when it differs from #1;
3. variant #2 followed by the year — only when a year is provided.

Duplicate queries (compared via :func:`normalize_text`) are dropped, so
punctuation-free titles never yield a redundant second HTTP request.
"""

from __future__ import annotations

import re
from typing import Optional

from utils.normalization import normalize_text

_WS_RE = re.compile(r"\s+")
# Any char that is not a word-char or whitespace is search noise for the
# site's engine (unicode dash variants included — they are not \w or \s).
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def search_query_variants(
    title: Optional[str],
    year: Optional[int] = None,
) -> list[str]:
    """Ordered, de-duplicated search queries for one item title."""
    base = _WS_RE.sub(" ", (title or "")).strip()

    variants: list[str] = []
    seen_keys: set[str] = set()

    def _add(candidate: str) -> None:
        candidate = _WS_RE.sub(" ", candidate).strip()
        key = normalize_text(candidate)
        if candidate and key and key not in seen_keys:
            seen_keys.add(key)
            variants.append(candidate)

    # Punctuation-only input ("...") has nothing worth searching for.
    if re.search(r"\w", base, re.UNICODE):
        _add(base)

    stripped = _PUNCT_RE.sub(" ", base).strip()
    _add(stripped)

    # A bare year with no title tokens would be a wasted request.
    if year and normalize_text(stripped):
        _add(f"{stripped} {year}")

    return variants


__all__ = ["search_query_variants"]
