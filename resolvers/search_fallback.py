"""Search-engine fallback discovery (Phase 8).

Two best-effort channels, tried in order:

1. The site's own HTML search (``/?s=<query>``) — verified working and
   returns clean content links.
2. DuckDuckGo's HTML endpoint — external dependency; failure here is
   tolerated and must never crash the resolver.

Every URL from either channel is filtered through the domain allowlist
and the movie/series path regexes before it becomes a candidate.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup

from httpclient.client import HttpClient, HttpError
from resolvers.models import SearchCandidate
from resolvers.url_policy import BASE_URL, safe_fetch_url, url_path_kind

logger = logging.getLogger("f2m.search")

_MAX_RESULTS_PER_CHANNEL = 6


def _dedupe_by_url(candidates: list[SearchCandidate]) -> list[SearchCandidate]:
    seen: set[str] = set()
    unique: list[SearchCandidate] = []
    for cand in candidates:
        if cand.url not in seen:
            seen.add(cand.url)
            unique.append(cand)
    return unique


def _filter_by_type(
    urls: list[str],
    item_type: str,
    method: str,
) -> list[SearchCandidate]:
    candidates: list[SearchCandidate] = []
    for url in urls[:_MAX_RESULTS_PER_CHANNEL]:
        safe = safe_fetch_url(url)
        if not safe:
            continue
        kind = url_path_kind(safe)
        expected = "series" if item_type == "series" else "movie"
        if kind != expected:
            continue
        candidates.append(SearchCandidate(url=safe, method=method))
    return candidates


def site_search_candidates(
    http: HttpClient,
    *,
    title: str,
    item_type: str,
) -> list[SearchCandidate]:
    """Search f2medi.top's own ``?s=`` page and extract content links."""
    try:
        response = http.get(
            BASE_URL + "/",
            params={"s": title},
            timeout=20.0,
            headers={"Referer": BASE_URL + "/"},
        )
    except HttpError as exc:
        logger.warning("[F2M] site search failed: %s", exc)
        return []

    if response.status_code != 200:
        logger.warning("[F2M] site search status=%d", response.status_code)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    hrefs = [
        a.get("href", "")
        for a in soup.select("a[href]")
    ]
    return _filter_by_type(hrefs, item_type, "search")


def duckduckgo_candidates(
    http: HttpClient,
    *,
    title: str,
    item_type: str,
) -> list[SearchCandidate]:
    """Last-resort external search. Tolerates total unavailability."""
    if item_type == "series":
        query = f'site:f2medi.top/series/ "{title}"'
    else:
        query = f'site:f2medi.top "{title}"'

    search_url = (
        "https://html.duckduckgo.com/html/"
        + "?q=" + urllib.parse.quote_plus(query)
    )

    try:
        response = http.get(search_url, timeout=20.0)
    except HttpError as exc:
        logger.warning("[SEARCH] duckduckgo unavailable: %s", type(exc).__name__)
        return []

    if response.status_code != 200:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    real_urls: list[str] = []

    for link in soup.select("a.result__a"):
        href = link.get("href", "")
        # DDG wraps targets as /l/?uddg=<urlencoded-real-url>&rut=...
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        target = parsed.get("uddg", [href])[0]
        target = urllib.parse.unquote(target)
        if target:
            real_urls.append(target)

    logger.info("[SEARCH] duckduckgo raw results: %d", len(real_urls))
    return _filter_by_type(real_urls, item_type, "search")


def search_fallback_candidates(
    http: HttpClient,
    *,
    title: str,
    item_type: str,
) -> list[SearchCandidate]:
    """Both fallback channels, de-duplicated, site search first."""
    combined = (
        site_search_candidates(http, title=title, item_type=item_type)
        + duckduckgo_candidates(http, title=title, item_type=item_type)
    )
    unique = _dedupe_by_url(combined)
    logger.info("[F2M] search fallback produced %d candidate(s)", len(unique))
    return unique
