"""Unit tests: direct slug candidates and TTL cache."""

import unittest

from resolvers.direct_resolver import (
    SERIES_SLUG_PATTERNS,
    direct_candidates,
    generate_series_candidates,
)
from utils.cache import TTLCache


class TestSlugCandidates(unittest.TestCase):
    def test_patterns_applied_and_ordered(self):
        slugs = generate_series_candidates("Ted Lasso")
        self.assertEqual(slugs[0], "ted-lasso")
        self.assertIn("ted-lasso-series", slugs)
        self.assertIn("zted-lasso-series", slugs)
        # All patterns produce a variant; no duplicates.
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertLessEqual(len(slugs), len(SERIES_SLUG_PATTERNS))

    def test_year_removed_from_slug(self):
        slugs = generate_series_candidates("Ted Lasso 2020")
        self.assertNotIn("2020", " ".join(slugs))

    def test_non_latin_title_yields_nothing(self):
        self.assertEqual(generate_series_candidates("داستان اسباب بازی"), [])

    def test_movies_never_get_direct_candidates(self):
        # Movie URLs embed an unpredictable numeric ID: guessing is banned.
        self.assertEqual(
            direct_candidates(title="The Shawshank Redemption", item_type="movie"),
            [],
        )


class TestTTLCache(unittest.TestCase):
    def test_set_get_roundtrip(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("k", {"v": 1})
        self.assertEqual(cache.get("k"), {"v": 1})

    def test_missing_key_returns_none(self):
        self.assertIsNone(TTLCache(ttl_seconds=60).get("nope"))

    def test_expiry(self):
        import time

        cache = TTLCache(ttl_seconds=0.05)
        cache.set("k", 42)
        time.sleep(0.08)
        self.assertIsNone(cache.get("k"))

    def test_lru_eviction(self):
        cache = TTLCache(ttl_seconds=60, max_entries=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # evicts "a"
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.get("c"), 3)

    def test_get_or_set(self):
        cache = TTLCache(ttl_seconds=60)
        calls = []

        def factory():
            calls.append(1)
            return "value"

        self.assertEqual(cache.get_or_set("k", factory), "value")
        self.assertEqual(cache.get_or_set("k", factory), "value")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
