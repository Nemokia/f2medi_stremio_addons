"""Live integration tests (Phase 16).

Runs real end-to-end resolution against f2medi.top. Skipped by default so
the unit suite stays offline-safe:

    F2MEDIA_LIVE=1 python -m unittest tests.test_integration_live -v

Required cases: Ted Lasso (series), The Shawshank Redemption (movie),
Avengers: Infinity War (movie).
"""

import os
import unittest

from parsers.f2medi_parser import parse_f2media_page
from resolvers import F2MediaResolver

_LIVE = os.environ.get("F2MEDIA_LIVE", "").strip().lower() in {"1", "true", "yes"}

CASES = [
    {
        "name": "Ted Lasso",
        "item_type": "series",
        "imdb_id": "tt10986410",
        "year": 2020,
    },
    {
        "name": "The Shawshank Redemption",
        "item_type": "movie",
        "imdb_id": "tt0111161",
        "year": 1994,
    },
    {
        "name": "Avengers: Infinity War",
        "item_type": "movie",
        "imdb_id": "tt4154756",
        "year": 2018,
    },
    {
        "name": "Avengers: Endgame",
        "item_type": "movie",
        "imdb_id": "tt4154796",
        "year": 2019,
    },
]


@unittest.skipUnless(_LIVE, "set F2MEDIA_LIVE=1 to run live integration tests")
class TestLiveResolution(unittest.TestCase):
    resolver = F2MediaResolver()

    def _run_case(self, case):
        result = self.resolver.resolve(
            title=case["name"],
            item_type=case["item_type"],
            imdb_id=case["imdb_id"],
            year=case["year"],
        )
        print(
            f"\n[INTEGRATION] {case['name']}: found={result.found} "
            f"method={result.method} score={round(result.score, 3)} url={result.url}"
        )

        self.assertTrue(result.found, f"{case['name']} was not resolved")
        self.assertIsNotNone(result.url)
        self.assertIn("f2medi.top", result.url)
        self.assertGreaterEqual(result.score, 0.5)

        page = parse_f2media_page(
            result.html, item_type=case["item_type"], url=result.url
        )
        print(
            f"[INTEGRATION] {case['name']}: parsed streams={len(page.streams)} "
            f"title={page.title!r}"
        )
        self.assertTrue(page.streams, "no streams parsed from validated page")
        return result, page

    def test_series_ted_lasso(self):
        result, page = self._run_case(CASES[0])
        self.assertEqual(page.item_type, "series")
        seasons = {s.season for s in page.streams}
        self.assertTrue(seasons, "no seasons extracted")

    def test_movie_shawshank_redemption(self):
        result, page = self._run_case(CASES[1])
        self.assertEqual(page.item_type, "movie")
        qualities = {s.quality for s in page.streams}
        self.assertTrue(any("1080" in q for q in qualities), qualities)
        langs = {s.lang_type for s in page.streams}
        self.assertIn("Dubbed", langs)   # ...-farsi-dubbed URL promises dubs
        self.assertIn("Subtitled", langs)

    def test_movie_avengers_infinity_war(self):
        result, page = self._run_case(CASES[2])
        self.assertEqual(page.item_type, "movie")
        self.assertTrue(page.streams)

    def test_movie_avengers_endgame(self):
        """Regression: punctuation-bearing title must resolve to WP id 175."""
        result, page = self._run_case(CASES[3])
        self.assertEqual(page.item_type, "movie")
        self.assertEqual(result.method, "wordpress")
        self.assertIn("/175/", result.url)
        self.assertTrue(page.streams)


if __name__ == "__main__":
    unittest.main(verbosity=2)
