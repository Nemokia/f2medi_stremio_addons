"""WordPress REST API discovery for f2medi.top (Phase 3).

Live-verified behavior:
* ``GET /wp-json/wp/v2/search?search=<q>&subtype=post|series&per_page=N``
  returns items ``{id, title, url, type, subtype}`` where movies are
  ``subtype="post"`` and series use the custom ``series`` post type.
* Movies live at ``/<numeric-id>/<slug>/`` — not guessable, which is why
  this API is the primary discovery channel.
* Every wp-json response begins with a UTF-8 BOM; parsing must go through
  :func:`httpclient.json_utils.parse_json_response`.
* The search engine fails on punctuation-bearing queries ("Avengers:
  Endgame" -> []) while the punctuation-free form matches ("Avengers
  Endgame" -> id 175), so discovery walks :func:`search_query_variants`
  lazily and stops at the first query that returns results.
"""

from __future__ import annotations

import logging
from typing import Iterator, Optional

from httpclient.client import HttpClient, HttpError
from httpclient.json_utils import parse_json_response
from resolvers.models import SearchCandidate
from resolvers.url_policy import BASE_URL, safe_fetch_url
from utils.query_variants import search_query_variants

logger = logging.getLogger("f2m.wp")

_SEARCH_ENDPOINT = "/wp-json/wp/v2/search"

# WP subtype values mapped to our item types.
# Verified valid subtypes on this site: post, page, series, collection,
# category, post_tag, any. Stremio "movie" maps to WP "post"; only these
# two mappings exist — do not invent more.
_SUBTYPE_BY_TYPE = {"movie": "post", "series": "series"}


def wp_subtype_for(item_type: str) -> Optional[str]:
    """Single source of truth: Stremio item type -> WordPress REST subtype.

    movie -> "post", series -> "series", anything else -> None (untyped).
    """
    return _SUBTYPE_BY_TYPE.get(item_type)


class WordPressResolver:
    """Thin, defensive client over the site's WP search endpoint."""

    def __init__(
        self,
        http: HttpClient,
        *,
        base_url: str = BASE_URL,
        per_page: int = 8,
    ) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.per_page = per_page

    def _search_once(
        self,
        search_term: str,
        *,
        subtype: Optional[str],
    ) -> list[SearchCandidate]:
        params = {
            "search": search_term,
            "per_page": self.per_page,
        }
        if subtype:
            params["subtype"] = subtype

        try:
            response = self.http.get(
                self.base_url + _SEARCH_ENDPOINT,
                params=params,
                timeout=15.0,
            )
        except HttpError as exc:
            logger.warning("[WP] search request failed: %s", exc)
            return []

        if response.status_code != 200:
            logger.warning("[WP] search status=%d", response.status_code)
            return []

        payload = parse_json_response(response)
        if not isinstance(payload, list):
            logger.warning("[WP] unexpected search payload type")
            return []

        candidates: list[SearchCandidate] = []
        seen_urls: set[str] = set()

        for entry in payload:
            if not isinstance(entry, dict):
                continue

            raw_url = entry.get("url") or ""
            url = safe_fetch_url(raw_url, base=self.base_url + "/")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            wp_id = entry.get("id")
            candidates.append(
                SearchCandidate(
                    url=url,
                    method="wordpress",
                    subtype=entry.get("subtype") or entry.get("type"),
                    wp_id=int(wp_id) if isinstance(wp_id, int) else None,
                    wp_title=_strip_html(entry.get("title") or ""),
                )
            )

        logger.info(
            "[WP] query=%r subtype=%s results=%d",
            search_term,
            subtype or "-",
            len(candidates),
        )
        return candidates

    def iter_discover(
        self,
        title: str,
        *,
        item_type: str,
        year: Optional[int] = None,
    ) -> Iterator[tuple[str, list[SearchCandidate]]]:
        """Lazily yield ``(stage_label, candidates)`` per search query.

        Query variants run in deterministic order and iteration stops as
        soon as a typed query returns results (early success). Only when
        *every* typed query came back empty does the pre-existing untyped
        safety net run once — for posts whose subtype was set
        inconsistently on the site.

        Laziness matters: each yielded batch performs its own network
        I/O, so later queries must only execute when the caller actually
        needs them (earlier candidates were empty or failed validation).
        """
        subtype = wp_subtype_for(item_type)

        got_results = False
        for index, query in enumerate(
            search_query_variants(title, year=year), start=1
        ):
            results = self._search_once(query, subtype=subtype)
            if results:
                got_results = True
                yield (f"wp-q{index}", results)

        if not got_results:
            # Untyped safety net with the original title, exactly once.
            results = self._search_once(title, subtype=None)
            if results:
                yield ("wp-untyped", results)

    def discover(
        self,
        title: str,
        *,
        item_type: str,
        year: Optional[int] = None,
    ) -> list[SearchCandidate]:
        """Eager convenience wrapper over :meth:`iter_discover`."""
        collected: list[SearchCandidate] = []
        for _, batch in self.iter_discover(
            title, item_type=item_type, year=year
        ):
            collected.extend(batch)
        return collected


def _strip_html(text: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", text).strip()
