"""Direct URL candidate generation — FALLBACK ONLY (Phase 7).

Movie URLs embed an unpredictable numeric prefix (``/3010/slug/``), so
direct guessing is only meaningful for series. Every generated URL still
goes through fetch + content validation before being trusted.
"""

from __future__ import annotations

import logging

from resolvers.models import SearchCandidate
from resolvers.url_policy import BASE_URL, safe_fetch_url
from utils.normalization import slugify

logger = logging.getLogger("f2m.direct")

# Slug shapes observed in live series URLs ("zted-lasso-series").
SERIES_SLUG_PATTERNS = (
    "{slug}",
    "{slug}-series",
    "z{slug}-series",
    "{slug}-tv",
    "{slug}-tv-series",
)


def generate_series_candidates(title: str) -> list[str]:
    """Ordered, de-duplicated slug variants for a series title."""
    base_slug = slugify(title)
    if not base_slug:
        return []

    seen: dict[str, None] = {}
    for pattern in SERIES_SLUG_PATTERNS:
        slug = pattern.format(slug=base_slug)
        seen.setdefault(slug, None)
    return list(seen)


def direct_candidates(
    *,
    title: str,
    item_type: str,
) -> list[SearchCandidate]:
    """Build direct-URL candidates; empty for movies (not guessable)."""
    if item_type != "series":
        return []

    candidates: list[SearchCandidate] = []
    for slug in generate_series_candidates(title):
        url = safe_fetch_url(f"{BASE_URL}/series/{slug}/")
        if url:
            candidates.append(SearchCandidate(url=url, method="direct"))

    logger.info("[F2M] direct candidates: %d", len(candidates))
    return candidates
