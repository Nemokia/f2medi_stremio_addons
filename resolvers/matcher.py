"""Multi-factor candidate scoring (Phase 5).

Candidates are scored before fetch (WP metadata + URL shape) and again
after fetch (page title, year, IMDb link). Evidence that is absent scores
0 — being unknown never earns points; conflicting evidence can veto.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional

from resolvers.models import CandidateScore, SearchCandidate
from resolvers.url_policy import url_path_kind
from utils.normalization import extract_year, normalize_text, normalize_title

logger = logging.getLogger("f2m.match")

_ASCII_RUN_RE = re.compile(r"[a-z0-9]+(?: [a-z0-9]+)*")
_IMDB_ID_RE = re.compile(r"tt\d{5,}")

# Hard gates: a candidate must agree on type and reach this title bar
# before its total score is even considered.
MIN_TITLE_SCORE_PREFETCH = 0.40
MIN_TOTAL_ACCEPT = 0.50


@dataclass
class MatchQuery:
    """What we are looking for, in normalized form."""

    title: str                        # raw title from Cinemeta
    item_type: str                    # "movie" | "series"
    year: Optional[int] = None
    imdb_id: Optional[str] = None     # e.g. "tt0111161"

    def __post_init__(self) -> None:
        self.normalized_title = normalize_title(self.title)
        if self.imdb_id and not self.imdb_id.startswith("tt"):
            self.imdb_id = None


def title_similarity(query_title: str, candidate_title: str) -> float:
    """Similarity in [0, 1] robust to mixed Persian/English titles.

    The site embeds the English title inside Persian marketing text
    ("دانلود سریال تد لاسو Ted Lasso بدون..."), so the latin runs of the
    candidate are extracted first; containment of either side counts as a
    near-match instead of punishing length differences.
    """
    q = normalize_title(query_title)
    c_raw = normalize_text(candidate_title)
    c_ascii = " ".join(_ASCII_RUN_RE.findall(c_raw))
    c_key = normalize_title(c_ascii) or normalize_title(c_raw)

    if not q or not c_key:
        return 0.0
    if q == c_key:
        return 1.0

    ratio = SequenceMatcher(None, q, c_key).ratio()
    if q in c_key or c_key in q:
        return max(0.85, ratio)

    return ratio


def _type_of_candidate(candidate: SearchCandidate) -> Optional[str]:
    if candidate.subtype == "series":
        return "series"
    if candidate.subtype == "post":
        return "movie"
    return url_path_kind(candidate.url)


def score_candidate_prefetch(
    candidate: SearchCandidate,
    query: MatchQuery,
) -> CandidateScore:
    """Score using only discovery metadata (no HTTP fetch needed)."""
    expected_type = (
        "series" if query.item_type == "series" else "movie"
    )

    actual_type = _type_of_candidate(candidate)
    type_match = 1.0 if actual_type == expected_type else 0.0

    title_source = candidate.wp_title or candidate.url
    title_match = title_similarity(query.title, title_source)

    year_match = 0.0
    candidate_year = extract_year(candidate.wp_title or "")
    if query.year is None or candidate_year is None:
        pass  # no year evidence on at least one side
    elif candidate_year == query.year:
        year_match = 1.0
    elif abs(candidate_year - query.year) == 1:
        # Off-by-one years are common release-date disagreements.
        year_match = 0.5

    url_kind = url_path_kind(candidate.url)
    url_match = (
        1.0 if url_kind == expected_type
        else 0.3 if url_kind is None
        else 0.0
    )

    return CandidateScore(
        type_match=type_match,
        title_match=round(title_match, 4),
        year_match=year_match,
        imdb_match=0.0,
        url_match=url_match,
    )


def passes_prefetch_gates(score: CandidateScore) -> bool:
    """Type must match exactly and the title must clear the bar."""
    if score.type_match < 1.0:
        return False
    return score.title_match >= MIN_TITLE_SCORE_PREFETCH


def apply_page_evidence(
    score: CandidateScore,
    *,
    query: MatchQuery,
    page_title: str,
    page_year: Optional[int],
    html_has_imdb_ids: Iterable[str] = (),
) -> CandidateScore:
    """Fold post-fetch evidence (title/year/imdb) into an existing score.

    Returns a new CandidateScore; the original is left untouched.
    """
    title_match = max(score.title_match, title_similarity(query.title, page_title))

    year_match = score.year_match
    if query.year is not None and page_year is not None:
        if page_year == query.year:
            year_match = 1.0
        elif abs(page_year - query.year) == 1:
            year_match = max(year_match, 0.5)
        else:
            year_match = 0.0

    imdb_match = 0.0
    ids = {i.lower() for i in html_has_imdb_ids}
    if query.imdb_id:
        if query.imdb_id.lower() in ids:
            imdb_match = 1.0
        elif ids:
            # Page links to a *different* title's IMDb entry: strong veto.
            imdb_match = 0.0
            title_match *= 0.6

    return CandidateScore(
        type_match=score.type_match,
        title_match=round(title_match, 4),
        year_match=year_match,
        imdb_match=imdb_match,
        url_match=score.url_match,
    )
