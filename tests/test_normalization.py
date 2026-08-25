"""Unit tests: text normalization, year extraction, slug generation."""

import unittest

from utils.normalization import extract_year, normalize_text, normalize_title, slugify


class TestNormalizeTitle(unittest.TestCase):
    def test_case_and_whitespace_folding(self):
        self.assertEqual(normalize_title("Ted Lasso"), "ted lasso")
        self.assertEqual(normalize_title("TED   lasso"), "ted lasso")

    def test_dash_variants(self):
        self.assertEqual(
            normalize_title("Avengers: Infinity War"),
            normalize_title("avengers–infinity—war"),
        )

    def test_year_stripped(self):
        self.assertEqual(normalize_title("Ted Lasso 2020"), "ted lasso")

    def test_persian_suffixes_stripped(self):
        # Site titles carry marketing suffixes; they must not break matching.
        title = "دانلود سریال Ted Lasso بدون سانسور با زیرنویس فارسی چسبیده"
        normalized = normalize_title(title)
        self.assertIn("ted", normalized)
        self.assertIn("lasso", normalized)
        self.assertNotIn("sansur", normalized)

    def test_persian_chars_unified(self):
        # Arabic yeh/kaf fold onto Persian forms.
        self.assertEqual(normalize_text("فاﺮسی"), normalize_text("فارسی"))
        self.assertIn("فارسی", normalize_text("فارسى"))

    def test_zero_width_removed(self):
        self.assertEqual(normalize_text("اسباب\u200cبازی"), "اسباببازی")

    def test_distinct_titles_stay_distinct(self):
        self.assertNotEqual(
            normalize_title("Movie A 2020"), normalize_title("Movie B 2020")
        )

    def test_empty_inputs(self):
        self.assertEqual(normalize_title(""), "")
        self.assertEqual(normalize_title(None), "")


class TestExtractYear(unittest.TestCase):
    def test_extracts_valid_year(self):
        self.assertEqual(extract_year("The Shawshank Redemption 1994"), 1994)
        self.assertEqual(extract_year("Toy Story 5 (2026) فصل اول"), 2026)

    def test_rejects_out_of_range(self):
        self.assertIsNone(extract_year("1899"))
        self.assertIsNone(extract_year("2100"))

    def test_no_year(self):
        self.assertIsNone(extract_year("President Curtis"))
        self.assertIsNone(extract_year(""))


class TestSlugify(unittest.TestCase):
    def test_basic_slug(self):
        self.assertEqual(slugify("Toy Story 5 (2026)"), "toy-story-5")

    def test_collapses_separators(self):
        self.assertEqual(slugify("Ted -- Lasso!!"), "ted-lasso")

    def test_non_latin_returns_empty(self):
        self.assertEqual(slugify("داستان اسباب بازی"), "")


if __name__ == "__main__":
    unittest.main()
