"""Post-fetch page validation for F2Media content pages.

A fetched URL is only trusted when the *content* proves it is the right
kind of page. The site never returns 404 for unknown URLs — it issues a
301 to ``/profile/`` (verified live) — so status codes alone are useless
here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

from resolvers.url_policy import (
    BASE_URL,
    is_profile_or_login_url,
    url_path_kind,
)
from utils.normalization import extract_year

logger = logging.getLogger("f2m.validate")

# Markers observed on Cloudflare interstitials (checked case-insensitively).
_CLOUDFLARE_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "attention required!",
    "challenge-platform",
    "cf-chl",
)

# Text markers that indicate a login/profile page via its <title>. The
# site also renders a persistent "login to watch online" banner on every
# page, so body text must never be used for this check (false-positive).
_LOGIN_TITLE_MARKERS = ("پروفایل", "ورود", "login", "profile", "register")

# Structure verified against live movie + series pages.
_MOVIE_SELECTOR = ".download-list"
_SERIES_SELECTOR = ".download-season"


@dataclass
class PageValidation:
    """Outcome of validating one fetched page."""

    ok: bool
    reason: str = ""
    title: str = ""
    year: Optional[int] = None
    canonical_url: Optional[str] = None


def looks_like_cloudflare(html: str) -> bool:
    """Detect Cloudflare challenge/interstitial pages."""
    if not html:
        return False
    lowered = html.lower()
    return any(marker in lowered for marker in _CLOUDFLARE_MARKERS)


def extract_canonical_url(
    soup: BeautifulSoup,
    *,
    base: str = BASE_URL + "/",
) -> Optional[str]:
    """Extract and absolutize ``<link rel="canonical">`` from a page."""
    tag = soup.select_one('link[rel="canonical"]')
    if not tag:
        return None
    href = tag.get("href")
    if not href:
        return None
    try:
        import urllib.parse

        return urllib.parse.urljoin(base, href.strip())
    except ValueError:
        return None


def _looks_like_login(soup: BeautifulSoup) -> bool:
    """Login/profile pages announce themselves in <title> ('پروفایل کاربری').

    Structural absence of download content is checked separately, so this
    only needs the title signal.
    """
    title_text = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    return any(marker in title_text for marker in _LOGIN_TITLE_MARKERS)


def validate_content_page(
    response: requests.Response,
    *,
    item_type: str,
) -> PageValidation:
    """Validate an HTTP response as a genuine movie/series content page.

    Checks (in order): HTTP status, Cloudflare challenge, profile/login
    redirect landing, expected download structure for the requested type,
    and extracts title/year/canonical for downstream matching.
    """
    if response.status_code != 200:
        return PageValidation(False, f"http {response.status_code}")

    html = response.text or ""

    if is_profile_or_login_url(str(response.url)):
        return PageValidation(False, "landed on profile/login")

    if looks_like_cloudflare(html):
        return PageValidation(False, "cloudflare challenge")

    if len(html) < 500:
        return PageValidation(False, "empty or tiny body")

    soup = BeautifulSoup(html, "html.parser")

    if _looks_like_login(soup):
        return PageValidation(False, "login wall detected in content")

    # A series page also contains .download-list (season-pack block without
    # links), so type checks must be ordered: series structure first.
    has_series_structure = soup.select_one(_SERIES_SELECTOR) is not None
    has_movie_structure = soup.select_one(f"{_MOVIE_SELECTOR} a.btn-download") is not None

    if item_type == "series":
        structural_ok = has_series_structure
        reason = "no season/download structure" if not structural_ok else ""
    elif item_type == "movie":
        structural_ok = has_movie_structure and not has_series_structure
        if not structural_ok:
            reason = (
                "page has series structure"
                if has_series_structure
                else "no movie download links"
            )
        else:
            reason = ""
    else:
        return PageValidation(False, f"unknown item_type {item_type!r}")

    if not structural_ok:
        return PageValidation(False, reason)

    title = ""
    h1 = soup.select_one("h1.entry-title") or soup.select_one("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
    elif soup.title:
        title = soup.title.get_text(" ", strip=True)

    canonical = extract_canonical_url(soup)
    if canonical:
        kind = url_path_kind(canonical)
        if kind and kind != item_type:
            return PageValidation(
                False,
                f"canonical type mismatch ({kind} != {item_type})",
            )

    return PageValidation(
        ok=True,
        title=title,
        year=extract_year(title),
        canonical_url=canonical,
    )
