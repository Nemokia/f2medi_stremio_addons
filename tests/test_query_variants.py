"""Unit tests: deterministic search query variant generation."""

import unittest

from utils.query_variants import search_query_variants


class TestSearchQueryVariants(unittest.TestCase):
    def test_endgame_produces_required_variants_in_order(self):
        self.assertEqual(
            search_query_variants("Avengers: Endgame", 2019),
            ["Avengers: Endgame", "Avengers Endgame", "Avengers Endgame 2019"],
        )

    def test_punctuation_free_title_not_duplicated(self):
        # Second variant would be identical -> must be dropped.
        self.assertEqual(
            search_query_variants("The Shawshank Redemption"),
            ["The Shawshank Redemption"],
        )

    def test_year_appended_only_when_provided(self):
        self.assertEqual(search_query_variants("Ted Lasso"), ["Ted Lasso"])
        self.assertEqual(
            search_query_variants("Ted Lasso", 2020),
            ["Ted Lasso", "Ted Lasso 2020"],
        )

    def test_dash_variants_normalized(self):
        self.assertIn(
            "Avengers Infinity War",
            search_query_variants("Avengers–Infinity—War", 2018),
        )
        # Hyphen is punctuation for the site's engine too.
        self.assertIn(
            "Spider Man No Way Home",
            search_query_variants("Spider-Man: No Way Home", 2021),
        )

    def test_extra_whitespace_collapsed(self):
        self.assertEqual(
            search_query_variants("  Avengers:   Endgame  "),
            ["Avengers: Endgame", "Avengers Endgame"],
        )

    def test_case_difference_is_a_duplicate(self):
        # normalize_text-based key: "ted lasso" vs "Ted Lasso" same query.
        variants = search_query_variants("Ted LASSO")
        self.assertEqual(variants, ["Ted LASSO"])

    def test_empty_and_useless_inputs(self):
        self.assertEqual(search_query_variants(""), [])
        self.assertEqual(search_query_variants(None), [])
        self.assertEqual(search_query_variants(None, 2019), [])
        self.assertEqual(search_query_variants("", 2019), [])
        self.assertEqual(search_query_variants("..."), [])

    def test_deterministic_across_calls(self):
        a = search_query_variants("Avengers: Endgame", 2019)
        b = search_query_variants("Avengers: Endgame", 2019)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
