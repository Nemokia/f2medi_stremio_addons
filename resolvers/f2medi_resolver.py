"""Top-level F2Media resolver orchestration (Phases 9-13, 17).

Pipeline (cheapest first):

    cache -> WordPress search -> pre-score & rank -> fetch/validate top
    candidates -> direct slug fallback (series) -> site/DDG search
    fallback -> best validated page

A candidate URL is only trusted after its *content* proves the right page
type and clears the score gates. Invalid URLs on this site redirect to
/profile/ rather than 404ing, so content validation is the real gate.
"""

from __future__ import annotations

import logging
from typing import Optional

from httpclient.client import HttpClient, HttpClientConfig, HttpError
from resolvers.direct_resolver import direct_candidates
from resolvers.matcher import (
    MIN_TOTAL_ACCEPT,
    MatchQuery,
    apply_page_evidence,
    passes_prefetch_gates,
    score_candidate_prefetch,
)
from resolvers.models import ResolverResult, SearchCandidate
from resolvers.search_fallback import search_fallback_candidates
from resolvers.url_policy import safe_fetch_url
from resolvers.validator import validate_content_page
from resolvers.wordpress_resolver import WordPressResolver
from utils.cache import TTLCache
from utils.normalization import normalize_title

logger = logging.getLogger("f2m")

# Request budget: never fetch more than this many candidate pages.
_MAX_CANDIDATES_FETCH = 4
_STOP_EARLY_SCORE = 0.85

_POSITIVE_TTL = 6 * 3600     # resolved pages rarely change
_NEGATIVE_TTL = 600          # brief negative cache to avoid hammering


class F2MediaResolver:
    """Facade coordinating discovery, validation, matching and caching."""

    def __init__(
        self,
        *,
        http: Optional[HttpClient] = None,
        cache: Optional[TTLCache] = None,
        base_url: str | None = None,
    ) -> None:
        self.http = http or HttpClient(HttpClientConfig.from_env())
        self.cache = cache or TTLCache(
            ttl_seconds=_POSITIVE_TTL, max_entries=48
        )
        # Short-lived negative cache so misses aren't hammered but are
        # retried again soon (content appears on the site over time).
        self._negative_cache = TTLCache(ttl_seconds=_NEGATIVE_TTL, max_entries=256)
        base_url = (base_url or "https://www.f2medi.top").rstrip("/")
        self.wordpress = WordPressResolver(self.http, base_url=base_url)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        *,
        title: str,
        item_type: str,
        imdb_id: Optional[str] = None,
        year: Optional[int] = None,
    ) -> ResolverResult:
        """Resolve an item to its F2Media content page.

        Never raises: any failure yields ``found=False``.
        """
        query = MatchQuery(
            title=title,
            item_type=item_type,
            year=year,
            imdb_id=imdb_id,
        )

        if not query.normalized_title:
            return ResolverResult.not_found("empty title")

        cache_key = self._cache_key(query)

        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.info("[F2M] cache hit %s", cache_key)
            return cached

        if self._negative_cache.get(cache_key) is not None:
            logger.debug("[F2M] negative cache hit")
            return ResolverResult.not_found("negative cache")

        result = self._resolve_uncached(query)

        if result.found:
            self.cache.set(cache_key, result)
            logger.info("[CACHE] stored %s", cache_key)
        else:
            self._negative_cache.set(cache_key, True)

        return result

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(query: MatchQuery) -> str:
        return (
            f"f2medi:{query.item_type}:"
            f"{query.imdb_id or 'NA'}:"
            f"{query.year or 'NA'}:"
            f"{query.normalized_title}"
        )

    def _resolve_uncached(self, query: MatchQuery) -> ResolverResult:
        logger.info(
            "[F2M] START title=%r type=%s year=%s imdb=%s",
            query.title,
            query.item_type,
            query.year,
            query.imdb_id or "-",
        )

        # Stage order per performance policy: WordPress first, then direct
        # slugs, then site/external search. A later stage only runs when no
        # earlier candidate survived fetch + validation.
        best: Optional[ResolverResult] = None

        for stage_name, stage_candidates in self._discovery_stages(query):
            if not stage_candidates:
                logger.info("[F2M] stage %s: no candidates", stage_name)
                continue

            ranked = self._rank_candidates(stage_candidates, query)
            best = self._best_validated(ranked, query)
            if best is not None:
                break

        if best is not None:
            logger.info(
                "[F2M] FOUND url=%s method=%s score=%.2f",
                best.url,
                best.method,
                best.score,
            )
            return best

        logger.info("[F2M] NO RESULT")
        return ResolverResult.not_found("no candidate passed validation")

    def _discovery_stages(self, query: MatchQuery):
        """Yield discovery stages lazily: wp variants -> direct -> search.

        A generator on purpose: each stage performs network I/O, so later
        stages must only execute when the loop actually reaches them
        (earlier stage produced nothing that validated). WordPress itself
        yields one stage per search-query variant, so a later variant is
        only queried when earlier candidates failed validation.
        """
        # Candidate pool dedupe across every query variant AND stage:
        # same WordPress id (or URL when no id) is never fetched twice.
        seen_keys: set[str] = set()

        for stage_name, batch in self.wordpress.iter_discover(
            query.title, item_type=query.item_type, year=query.year
        ):
            yield (
                f"wordpress[{stage_name}]",
                _dedupe(batch, seen_keys),
            )

        if query.item_type == "series":
            yield (
                "direct",
                _dedupe(
                    direct_candidates(
                        title=query.title, item_type=query.item_type
                    ),
                    seen_keys,
                ),
            )

        yield (
            "search",
            _dedupe(
                search_fallback_candidates(
                    self.http,
                    title=query.title,
                    item_type=query.item_type,
                ),
                seen_keys,
            ),
        )

    def _rank_candidates(
        self,
        candidates: list[SearchCandidate],
        query: MatchQuery,
    ) -> list[tuple[SearchCandidate, object]]:
        scored = []
        for cand in candidates:
            score = score_candidate_prefetch(cand, query)
            if not passes_prefetch_gates(score):
                logger.debug(
                    "[MATCH] gated out %s (title=%.2f)",
                    cand.url,
                    score.title_match,
                )
                continue
            scored.append((cand, score))

        scored.sort(key=lambda pair: pair[1].total, reverse=True)
        for cand, score in scored[:3]:
            logger.info(
                "[MATCH] candidate %s total=%.2f title=%.2f",
                cand.url,
                score.total,
                score.title_match,
            )
        return scored

    def _best_validated(
        self,
        ranked: list[tuple[SearchCandidate, object]],
        query: MatchQuery,
    ) -> Optional[ResolverResult]:
        """Fetch+validate ranked candidates until one clears the gates."""
        best: Optional[ResolverResult] = None

        for candidate, prefetch_score in ranked[:_MAX_CANDIDATES_FETCH]:
            result = self._try_candidate(candidate, prefetch_score, query)
            if result is None:
                continue
            if best is None or result.score > best.score:
                best = result
            if best.score >= _STOP_EARLY_SCORE:
                logger.info("[MATCH] early exit score=%.2f", best.score)
                break

        return best

    def _try_candidate(
        self,
        candidate: SearchCandidate,
        prefetch_score,
        query: MatchQuery,
    ) -> Optional[ResolverResult]:
        url = safe_fetch_url(candidate.url)
        if not url:
            return None

        logger.info("[HTTP] fetching candidate %s", url)
        try:
            response = self.http.get(url, timeout=25.0)
        except HttpError as exc:
            logger.warning("[HTTP] candidate fetch failed: %s", exc)
            return None

        validation = validate_content_page(response, item_type=query.item_type)
        if not validation.ok:
            logger.info("[F2M] rejected %s (%s)", url, validation.reason)
            return None

        imdb_ids = _extract_imdb_ids(response.text)
        final_score = apply_page_evidence(
            prefetch_score,
            query=query,
            page_title=validation.title,
            page_year=validation.year,
            html_has_imdb_ids=imdb_ids,
        )

        logger.info(
            "[MATCH] page score total=%.2f title=%.2f year=%.2f imdb=%.2f",
            final_score.total,
            final_score.title_match,
            final_score.year_match,
            final_score.imdb_match,
        )

        if final_score.total < MIN_TOTAL_ACCEPT:
            logger.info(
                "[F2M] rejected %s (score %.2f below %.2f)",
                url,
                final_score.total,
                MIN_TOTAL_ACCEPT,
            )
            return None

        # Phase 10: prefer canonical; re-validate when it differs.
        html = response.text
        final_url = str(response.url)
        canonical = validation.canonical_url
        if canonical:
            canonical_safe = safe_fetch_url(canonical)
            if canonical_safe and canonical_safe.rstrip("/") != final_url.rstrip("/"):
                logger.info("[F2M] canonical differs, refetching %s", canonical_safe)
                try:
                    canon_resp = self.http.get(canonical_safe, timeout=25.0)
                    canon_validation = validate_content_page(
                        canon_resp, item_type=query.item_type
                    )
                    if canon_validation.ok:
                        html = canon_resp.text
                        final_url = str(canon_resp.url)
                    else:
                        logger.warning(
                            "[F2M] canonical failed validation, keeping original"
                        )
                except HttpError as exc:
                    logger.warning("[F2M] canonical refetch failed: %s", exc)

        return ResolverResult(
            found=True,
            url=final_url,
            html=html,
            title=validation.title,
            year=validation.year or query.year,
            item_type=query.item_type,
            score=final_score.total,
            method=candidate.method,
        )


def _extract_imdb_ids(html: str) -> list[str]:
    import re

    return sorted(set(re.findall(r"imdb\.com/title/(tt\d{5,})", html or "")))


def _candidate_key(candidate: SearchCandidate) -> str:
    """Stable pool identity: WordPress id when known, else canonical URL."""
    if candidate.wp_id is not None:
        return f"wp-id:{candidate.wp_id}"
    return candidate.url


def _dedupe(
    candidates: list[SearchCandidate],
    seen_keys: set[str],
) -> list[SearchCandidate]:
    """Filter candidates already present in the shared discovery pool."""
    unique: list[SearchCandidate] = []
    for cand in candidates:
        key = _candidate_key(cand)
        if key not in seen_keys:
            seen_keys.add(key)
            unique.append(cand)
    return unique


__all__ = ["F2MediaResolver", "ResolverResult"]
