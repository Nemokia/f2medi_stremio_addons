"""Title/text normalization for multilingual (Persian/English) matching.

Two levels are provided:

* :func:`normalize_text` — light cleanup: unicode folding, Persian/Arabic
  character unification, zero-width characters, dash variants, whitespace.
* :func:`normalize_title` — :func:`normalize_text` plus removal of years,
  quality/marketing suffixes, and punctuation, producing a comparison key.

The aggressive level must stay conservative enough that two different
movies never collapse into the same key.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

# Persian-specific characters unified onto canonical forms.
_CHAR_FOLDS = {
    # Arabic yeh/kaf/alef-maqsura -> Persian forms
    "ي": "ی",
    "ى": "ی",
    "ك": "ک",
    # Arabic presentation variants of heh
    "ة": "ه",
    "ۀ": "ه",
    # Alef variants
    "أ": "ا",
    "إ": "ا",
    "آ": "ا",
    "ٱ": "ا",
}

_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\u200e\u200f\u2060]")
# ZWNJ (\u200c) is handled above; remaining Arabic Tatweel also removed.
_KASHIDA_RE = re.compile(r"\u0640")

_DASH_CHARS = "‐‑‒–—―−﹘﹣－"
_DASH_RE = re.compile(f"[{re.escape(_DASH_CHARS)}]")

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

# Common marketing/quality suffixes stripped from titles before compare.
_SUFFIX_TOKENS = {
    "farsi",
    "dubbed",
    "duble",
    "dub",
    "sub",
    "hardsub",
    "subtitle",
    "subtitles",
    "sansur",
    "sansor",
    "bedone",
    "zirnevis",
    "zirnevise",
    "farisi",
    "faarsi",
    "complete",
    "full",
    "series",
    "tv",
    "season",
    "web",
    "dl",
    "webdl",
    "webrip",
    "bluray",
    "brrip",
    "dvdrip",
    "hdrip",
    "1080p",
    "720p",
    "480p",
    "2160p",
    "4k",
    "x264",
    "x265",
    "hevc",
    "10bit",
    "8bit",
}


def normalize_text(value: Optional[str]) -> str:
    """Lightly normalize free text for comparison.

    Handles unicode NFKC folding, lowercase, Persian/Arabic character
    differences, zero-width joiners, dash variants and whitespace runs.
    """
    if not value:
        return ""

    text = unicodedata.normalize("NFKC", value)
    text = text.lower()

    text = "".join(_CHAR_FOLDS.get(ch, ch) for ch in text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _KASHIDA_RE.sub("", text)
    text = _DASH_RE.sub("-", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_title(value: Optional[str]) -> str:
    """Produce a comparison key from a movie/series title.

    Applies :func:`normalize_text`, then removes years, punctuation and
    common quality/language suffix tokens. Distinct titles remain distinct:
    only clearly non-identifying tokens are dropped.
    """
    text = normalize_text(value)
    if not text:
        return ""

    text = _YEAR_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)

    tokens = [t for t in text.split() if t]
    # Drop suffix/quality tokens only while at least one identifying
    # token remains, so "Movie 4K" keeps meaning but never becomes "".
    identifying = [t for t in tokens if t not in _SUFFIX_TOKENS]
    kept = identifying or tokens

    return " ".join(kept)


def extract_year(value: Optional[str]) -> Optional[int]:
    """Extract the first plausible production year (1900-2099) from text."""
    if not value:
        return None

    match = _YEAR_RE.search(normalize_text(value))
    if not match:
        return None

    year = int(match.group(0))
    return year if 1900 <= year <= 2099 else None


def slugify(value: str) -> str:
    """Convert a latin-script title to a URL slug candidate.

    Only ASCII alphanumerics survive; everything else becomes a dash.
    Non-latin-only input yields an empty string (caller decides fallback).
    """
    text = normalize_text(value)
    text = _YEAR_RE.sub("", text)
    slug = re.sub(r"[^a-z0-9\s-]", "", text)
    slug = re.sub(r"[\s-]+", "-", slug).strip("-")
    return slug
