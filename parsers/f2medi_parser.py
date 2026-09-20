"""Extract streams and metadata from a validated F2Media page (Phase 11).

Selectors below were verified against live pages:

Movie pages
    ``.download-list.dubbled`` / ``.download-list.hardsub`` blocks, each
    row (``li``) holding a quality label ``span.text[dir="ltr"]`` and an
    ``a.btn-download`` link.

Series pages
    One or more ``.download-season`` groups. Each group holds season
    buttons (``> button[data-bs-target]``) pointing at collapsible boxes;
    inside a box, every ``li.bg-body`` row is one quality with episode
    blocks under ``.series-downloaditems .d-flex`` whose last anchor is
    the actual download link ("قسمت NN").

A series page also contains a ``.download-list`` block (season-pack rows
without ``a.btn-download``), so the parser keys off ``.download-season``
presence — same rule as the validator.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from resolvers.models import F2MediaPage, ParsedStream
from utils.normalization import extract_year

logger = logging.getLogger("f2m.parser")

_EPISODE_RE = re.compile(r"\d{1,3}")

# Season buttons use Persian ordinal words ("فصل اول"), never digits.
_PERSIAN_ORDINALS = {
    "اول": 1,
    "دوم": 2,
    "سوم": 3,
    "چهارم": 4,
    "پنجم": 5,
    "ششم": 6,
    "هفتم": 7,
    "هشتم": 8,
    "نهم": 9,
    "دهم": 10,
    "یازدهم": 11,
    "دوازدهم": 12,
    "سیزدهم": 13,
    "چهاردهم": 14,
    "پانزدهم": 15,
}

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _to_ascii_digits(text: str) -> str:
    return text.translate(_PERSIAN_DIGITS)


def _season_number(season_text: str) -> Optional[str]:
    """Extract the season number from a button label.

    Handles 'فصل اول ...' (ordinal word), 'فصل 2' and Persian digits.
    Returns zero-padded string or None when no season marker is found.
    """
    if not season_text:
        return None

    normalized = _to_ascii_digits(_clean(season_text))
    digit_match = _EPISODE_RE.search(normalized)
    if digit_match:
        return f"{int(digit_match.group()):02d}"

    for word, number in _PERSIAN_ORDINALS.items():
        if word in normalized:
            return f"{number:02d}"

    return None


def _clean(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _quality_label(row: BeautifulSoup) -> str:
    tag = row.select_one('span.text[dir="ltr"]')
    return _clean(tag.get_text(" ", strip=True)) if tag else "Unknown"


def parse_f2media_page(
    html: str,
    *,
    item_type: str,
    url: str = "",
) -> F2MediaPage:
    """Parse validated HTML into a :class:`F2MediaPage`."""
    soup = BeautifulSoup(html, "html.parser")
    page = F2MediaPage(url=url, item_type=item_type)

    h1 = soup.select_one("h1.entry-title") or soup.select_one("h1")
    if h1:
        page.title = _clean(h1.get_text(" ", strip=True))
        page.year = extract_year(page.title)

    poster = soup.select_one("figure.entry-poster img")
    if poster:
        page.poster = poster.get("src") or poster.get("data-src") or ""

    excerpt = soup.select_one(".entry-excerpt p")
    if excerpt:
        page.description = _clean(excerpt.get_text(" ", strip=True))

    rating_tag = soup.select_one('a[href*="imdb.com"] strong')
    if rating_tag:
        page.imdb_rating = _clean(rating_tag.get_text(" ", strip=True))

    page.genres = [
        _clean(a.get_text(" ", strip=True))
        for a in soup.select(".entry-genres a")
    ]

    is_series = soup.select_one(".download-season") is not None
    if is_series:
        page.streams = _parse_series(soup)
    else:
        page.streams = _parse_movies(soup)

    logger.info(
        "[PARSER] type=%s streams=%d",
        "series" if is_series else "movie",
        len(page.streams),
    )
    return page


def _parse_movies(soup: BeautifulSoup) -> list[ParsedStream]:
    streams: list[ParsedStream] = []

    for block in soup.select(".download-list"):
        classes = block.get("class", [])
        lang_type = "Dubbed" if "dubbled" in classes else "Subtitled"

        for row in block.select("li"):
            link = row.select_one("a.btn-download")
            if not link:
                continue

            href = link.get("href", "")
            if not href:
                continue

            streams.append(
                ParsedStream(
                    kind="movie",
                    quality=_quality_label(row),
                    url=href,
                    lang_type=lang_type,
                )
            )

    return streams


def _parse_series(soup: BeautifulSoup) -> list[ParsedStream]:
    streams: list[ParsedStream] = []

    for group in soup.select(".download-season"):
        for button in group.select(":scope > button[data-bs-target]"):
            target_id = button.get("data-bs-target", "")
            if not target_id.startswith("#"):
                continue

            box = soup.select_one(target_id)
            if box is None:
                continue

            season_text = _clean(button.get_text(" ", strip=True))
            season_number = _season_number(season_text)

            for row in box.select("li.bg-body"):
                quality = _quality_label(row)

                for episode_block in row.select(".series-downloaditems .d-flex"):
                    anchors = [a for a in episode_block.select("a[href]") if a.get("href")]
                    if not anchors:
                        continue

                    # The last anchor carries the real download URL; earlier
                    # ones are page links / placeholders ("#").
                    href = anchors[-1]["href"]
                    episode_text = _to_ascii_digits(
                        _clean(anchors[-1].get_text(" ", strip=True))
                    )
                    ep_match = _EPISODE_RE.search(episode_text)
                    if not ep_match:
                        continue

                    streams.append(
                        ParsedStream(
                            kind="series",
                            quality=quality,
                            url=href,
                            season=season_number,
                            episode=f"{int(ep_match.group()):02d}",
                        )
                    )

    return streams
