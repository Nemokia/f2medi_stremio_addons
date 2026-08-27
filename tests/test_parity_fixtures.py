"""Golden parity tests: fixtures at repo root must always parse identically.

GOLDEN expectations below were captured with the ORIGINAL BeautifulSoup /
html.parser stack (Stage A0 of the zero-dependency port) via a live run of
``validate_content_page`` + ``parse_f2media_page`` against the three saved
pages. They pin observable parser output — never internals — so any engine
that keeps these green is behaviorally compatible with bs4 for this site.

If the site changes markup: save a new page at repo root, regenerate this
file's GOLDEN with the capture snippet, update ``FIXTURES``, and adapt
selectors per README's troubleshooting guide.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from parsers.f2medi_parser import parse_f2media_page
from resolvers.validator import validate_content_page

_REPO = Path(__file__).resolve().parent.parent

GOLDEN: dict[str, dict] = {
    "president_curtis": {
        "fixture": "president-curtis.html",
        "kind": "series",
        "page_title": "President Curtis",
        "page_year": None,
        "imdb_rating": "",
        "genres": [
            "انیمیشن",
            "انیمیشن",
            "علمی تخیلی",
            "علمی تخیلی",
            "کمدی",
            "کمدی",
        ],
        "poster_suffix": "jpg",
        "stream_count": 25,
        "qualities": [
            "WEB-DL 1080p",
            "WEB-DL 1080p 10bit x265",
            "WEB-DL 480p",
            "WEB-DL 720p",
            "WEB-DL 720p 10bit x265",
        ],
        "seasons": ["01"],
        "episodes": ["01", "02", "03", "04", "05"],
        "lang_types": [],
        "mkv_count": 25,
        "mka_count": 0,
    },
    "shawshank": {
        "fixture": "The Shawshank Redemption .html",
        "kind": "movie",
        "page_title": "The Shawshank Redemption 1994",
        "page_year": 1994,
        "imdb_rating": "9.3",
        "genres": ["درام", "درام"],
        "poster_suffix": "jpg",
        "stream_count": 11,
        "qualities": [
            "BluRay 1080p",
            "BluRay 1080p 10bit x265",
            "BluRay 480p",
            "BluRay 4K 2160p 10bit SDR",
            "BluRay 720p",
            "BluRay 720p 10bit x265",
            "صوت دوبله فارسی",
        ],
        "seasons": [],
        "episodes": [],
        "lang_types": ["Dubbed", "Subtitled"],
        "mkv_count": 9,
        "mka_count": 2,
    },
    "toy_story_5": {
        "fixture": "Toy Story 5.html",
        "kind": "movie",
        "page_title": "Toy Story 5 2026",
        "page_year": 2026,
        "imdb_rating": "",
        "genres": [
            "انیمیشن",
            "انیمیشن",
            "ماجراجویی",
            "ماجراجویی",
            "کمدی",
            "کمدی",
        ],
        "poster_suffix": "jpg",
        "stream_count": 16,
        "qualities": [
            "WEB-DL 1080p",
            "WEB-DL 1080p 10bit x265",
            "WEB-DL 1080p Full HD",
            "WEB-DL 480p",
            "WEB-DL 4K 2160p 10bit HDR",
            "WEB-DL 720p",
            "WEB-DL 720p 10bit x265",
            "صوت دوبله فارسی",
        ],
        "seasons": [],
        "episodes": [],
        "lang_types": ["Dubbed", "Subtitled"],
        "mkv_count": 13,
        "mka_count": 3,
    },
}


class _StubResponse:
    """Duck-typed response for :func:`validate_content_page`."""

    def __init__(self, html: str):
        self.status_code = 200
        self.text = html
        self.url = f"https://www.f2medi.top/x/"


class TestGoldenParity(unittest.TestCase):
    """Every fixture must still parse to exactly its captured values."""

    def _load(self, key: str) -> tuple[str, str]:
        name = GOLDEN[key]["fixture"]
        html = (_REPO / name).read_text(encoding="utf-8", errors="replace")
        return key, html

    def test_all_fixtures_present(self):
        missing = [
            g["fixture"]
            for g in GOLDEN.values()
            if not (_REPO / g["fixture"]).exists()
        ]
        self.assertEqual(missing, [], "missing fixture files")

    def test_each_fixture_parses_to_golden(self):
        for key in sorted(GOLDEN):
            with self.subTest(fixture=key):
                _, html = self._load(key)
                expected = GOLDEN[key]

                validation = validate_content_page(
                    _StubResponse(html), item_type=expected["kind"]
                )
                self.assertTrue(
                    validation.ok,
                    f"{key}: expected kind {expected['kind']} to validate "
                    f"(reason={validation.reason})",
                )
                self.assertEqual(validation.title, expected["page_title"])
                self.assertEqual(validation.year, expected["page_year"])

                page = parse_f2media_page(
                    html, item_type=expected["kind"], url=str(_REPO)
                )
                streams = page.streams

                self.assertEqual(page.title, expected["page_title"])
                self.assertEqual(page.year, expected["page_year"])
                self.assertEqual(page.imdb_rating, expected["imdb_rating"])
                self.assertEqual(sorted(page.genres), expected["genres"])

                suffix = (
                    page.poster.rsplit(".", 1)[-1]
                    if "." in page.poster
                    else ""
                )
                self.assertEqual(suffix, expected["poster_suffix"])
                self.assertTrue(page.poster.startswith("http"), page.poster)

                self.assertEqual(len(streams), expected["stream_count"])
                self.assertEqual(
                    sorted({s.quality for s in streams}),
                    expected["qualities"],
                )
                self.assertEqual(
                    sorted({s.season for s in streams if s.season}),
                    expected["seasons"],
                )
                self.assertEqual(
                    sorted({e for e in (s.episode for s in streams) if e}),
                    expected["episodes"],
                )
                self.assertEqual(
                    sorted({s.lang_type for s in streams if s.lang_type}),
                    expected["lang_types"],
                )
                self.assertEqual(
                    sum(1 for s in streams if s.url.lower().endswith(".mkv")),
                    expected["mkv_count"],
                )
                self.assertEqual(
                    sum(1 for s in streams if s.url.lower().endswith(".mka")),
                    expected["mka_count"],
                )
                for s in streams:
                    self.assertTrue(s.url.startswith("http"), s.url)


if __name__ == "__main__":
    unittest.main(verbosity=2)
