"""Data models shared by the F2Media resolver components.

All resolver outputs are typed dataclasses — no ad-hoc dicts cross
module boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SearchCandidate:
    """A URL candidate produced by any discovery layer."""

    url: str
    method: str                      # "wordpress" | "direct" | "search"
    subtype: Optional[str] = None    # WP subtype: "post" (movie) | "series"
    wp_id: Optional[int] = None
    wp_title: Optional[str] = None   # raw title text from the WP result

    def __post_init__(self) -> None:
        self.url = self.url.strip() if self.url else ""


@dataclass
class CandidateScore:
    """Multi-factor score for one candidate against one query item."""

    type_match: float = 0.0
    title_match: float = 0.0
    year_match: float = 0.0
    imdb_match: float = 0.0
    url_match: float = 0.0

    # Weights: title dominates; type and year are strong signals; imdb is
    # only usable when the page actually exposes it; url is weakest.
    WEIGHTS = {
        "type": 0.25,
        "title": 0.45,
        "year": 0.15,
        "imdb": 0.10,
        "url": 0.05,
    }

    @property
    def total(self) -> float:
        w = self.WEIGHTS
        return round(
            (
                self.type_match * w["type"]
                + self.title_match * w["title"]
                + self.year_match * w["year"]
                + self.imdb_match * w["imdb"]
                + self.url_match * w["url"]
            ),
            4,
        )


@dataclass
class ResolverResult:
    """Final outcome of resolving an item to an F2Media content page."""

    found: bool
    url: Optional[str] = None
    html: Optional[str] = None       # validated page HTML (for the parser)
    title: Optional[str] = None      # page title as seen on the site
    year: Optional[int] = None
    item_type: Optional[str] = None  # "movie" | "series"
    score: float = 0.0
    method: Optional[str] = None     # discovery method that produced it

    @classmethod
    def not_found(cls, reason: str = "") -> "ResolverResult":
        return cls(found=False, title=reason or None)


@dataclass
class ParsedStream:
    """One downloadable quality/episode entry parsed from a content page."""

    kind: str                        # "movie" | "series"
    quality: str
    url: str
    lang_type: Optional[str] = None  # movies: "Dubbed" | "Subtitled"
    season: Optional[str] = None     # series only
    episode: Optional[str] = None    # series only


@dataclass
class F2MediaPage:
    """Structured extraction of a validated F2Media content page."""

    url: str
    title: str = ""
    year: Optional[int] = None
    item_type: str = ""              # "movie" | "series"
    poster: str = ""
    description: str = ""
    imdb_rating: str = ""
    genres: list[str] = field(default_factory=list)
    streams: list[ParsedStream] = field(default_factory=list)
