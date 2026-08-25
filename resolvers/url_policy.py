"""URL security policy and structure rules for f2medi.top.

Every candidate URL must pass :func:`normalize_candidate_url` and
:func:`is_allowed_url` before any fetch is attempted. This is the single
choke-point guarding against SSRF / arbitrary-host fetching.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Optional

BASE_URL = "https://www.f2medi.top"

# Only hosts serving F2Media content pages may be fetched. The site has
# migrated domains at least twice (film2media.top -> fardabin.top ->
# f2medi.top); old hosts now redirect to a login/profile page.
ALLOWED_HOSTS = frozenset({"f2medi.top", "www.f2medi.top"})

# Verified live URL structures:
#   movie:  https://www.f2medi.top/3010/the-shawshank-redemption-1994-farsi-dubbed/
#   series: https://www.f2medi.top/series/zted-lasso-series/
MOVIE_URL_RE = re.compile(r"^/(?P<post_id>\d+)/(?P<slug>[a-z0-9-]+)/?$")
SERIES_URL_RE = re.compile(r"^/series/(?P<slug>[a-z0-9-]+)/?$")

PROFILE_PATH = "/profile/"


def normalize_candidate_url(
    url: str,
    *,
    base: str = BASE_URL + "/",
) -> Optional[str]:
    """Resolve a candidate against the site base; return absolute http(s) URL.

    Rejects non-http(s) schemes, protocol-relative tricks, credentials in
    the URL, and anything that fails to parse. Returns ``None`` instead of
    raising so callers can simply skip bad candidates.
    """
    if not url or not url.strip():
        return None

    try:
        joined = urllib.parse.urljoin(base, url.strip())
        parsed = urllib.parse.urlparse(joined)
    except ValueError:
        return None

    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None

    # Rebuild without fragment to avoid cache-key divergence on #anchors.
    clean = parsed._replace(fragment="", params="")
    return urllib.parse.urlunparse(clean)


def is_allowed_url(url: str) -> bool:
    """True when ``url`` points at an explicitly allowed host."""
    try:
        host = urllib.parse.urlparse(url).hostname
    except ValueError:
        return False
    if not host:
        return False
    return host.lower() in ALLOWED_HOSTS


def url_path_kind(url: str) -> Optional[str]:
    """Classify an allowed URL as 'movie' | 'series' | None by path shape."""
    try:
        path = urllib.parse.urlparse(url).path
    except ValueError:
        return None

    if SERIES_URL_RE.match(path):
        return "series"
    if MOVIE_URL_RE.match(path):
        return "movie"
    return None


def is_profile_or_login_url(url: str) -> bool:
    """Detect the site's soft-failure landing pages."""
    try:
        path = urllib.parse.urlparse(url).path.lower().rstrip("/")
    except ValueError:
        return True
    return path in {"/profile", "/login", "/wp-login", "/register"}


def safe_fetch_url(url: str, *, base: str = BASE_URL + "/") -> Optional[str]:
    """Normalize then allowlist-check a URL. The gatekeeper for all fetches."""
    normalized = normalize_candidate_url(url, base=base)
    if normalized is None or not is_allowed_url(normalized):
        return None
    return normalized
