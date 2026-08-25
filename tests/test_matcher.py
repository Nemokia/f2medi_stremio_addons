"""Unit tests: candidate scoring — movie/series/year matching and rejection."""

import unittest

from resolvers.matcher import (
    MatchQuery,
    passes_prefetch_gates,
    score_candidate_prefetch,
)
from resolvers.models import SearchCandidate


def wp_candidate(url, subtype, title):
    return SearchCandidate(url=url, method="wordpress", subtype=subtype, wp_title=title)


TED_WP_TITLE = "دانلود سریال تد لاسو Ted Lasso بدون سانسور با زیرنویس فارسی چسبیده"
SHAWSHANK_WP_TITLE = (
    "دانلود فیلم رستگاری در شاوشنک The Shawshank Redemption 1994 "
    "بدون سانسور با زیرنویس فارسی چسبیده"
)
ENDGAME_WP_TITLE = (
    "دانلود دوبله فارسی فیلم انتقام جویان پایان بازی Avengers Endgame 2019"
)


class TestSeriesMatching(unittest.TestCase):
    def test_series_candidate_matches(self):
        query = MatchQuery(title="Ted Lasso", item_type="series", year=2020)
        cand = wp_candidate(
            "https://www.f2medi.top/series/zted-lasso-series/", "series", TED_WP_TITLE
        )
        score = score_candidate_prefetch(cand, query)
        self.assertTrue(passes_prefetch_gates(score))
        self.assertEqual(score.type_match, 1.0)
        self.assertGreaterEqual(score.title_match, 0.85)

    def test_series_query_rejects_movie_result(self):
        query = MatchQuery(title="Ted Lasso", item_type="series", year=2020)
        cand = wp_candidate(
            "https://www.f2medi.top/123/ted-lasso-2020/", "post", TED_WP_TITLE
        )
        score = score_candidate_prefetch(cand, query)
        self.assertFalse(passes_prefetch_gates(score))


class TestMovieMatching(unittest.TestCase):
    def test_movie_candidate_matches(self):
        query = MatchQuery(
            title="The Shawshank Redemption", item_type="movie", year=1994
        )
        cand = wp_candidate(
            "https://www.f2medi.top/3010/the-shawshank-redemption-1994-farsi-dubbed/",
            "post",
            SHAWSHANK_WP_TITLE,
        )
        score = score_candidate_prefetch(cand, query)
        self.assertTrue(passes_prefetch_gates(score))
        self.assertEqual(score.type_match, 1.0)
        self.assertEqual(score.year_match, 1.0)

    def test_movie_query_rejects_series_result(self):
        query = MatchQuery(title="Ted Lasso", item_type="movie")
        cand = wp_candidate(
            "https://www.f2medi.top/series/zted-lasso-series/",
            "series",
            TED_WP_TITLE,
        )
        score = score_candidate_prefetch(cand, query)
        self.assertFalse(passes_prefetch_gates(score))


class TestAvengersMatching(unittest.TestCase):
    """Live-verified Endgame discovery case (movie -> subtype=post)."""

    def _query(self):
        return MatchQuery(
            title="Avengers: Endgame", item_type="movie",
            year=2019, imdb_id="tt4154796",
        )

    def _endgame_candidate(self):
        return wp_candidate(
            "https://www.f2medi.top/175/%d8%af%d8%a7%d9%86%d9%84%d9%88%d8%af"
            "-%d9%81%db%8c%d9%84%d9%85-avengers-endgame-2019/",
            "post",
            ENDGAME_WP_TITLE,
        )

    def test_persian_english_candidate_matches(self):
        score = score_candidate_prefetch(self._endgame_candidate(), self._query())
        self.assertTrue(passes_prefetch_gates(score))
        self.assertEqual(score.title_match, 1.0)  # colon/year/marketing ignored
        self.assertEqual(score.year_match, 1.0)
        self.assertGreaterEqual(score.total, 0.85)  # early-exit territory

    def test_other_avengers_movie_ranks_below_and_cannot_exit_early(self):
        infinity_war = wp_candidate(
            "https://www.f2medi.top/325/x/", "post",
            "دانلود دوبله فارسی فیلم انتقام جویان جنگ ابدیت "
            "Avengers: Infinity War 2018",
        )
        good = score_candidate_prefetch(self._endgame_candidate(), self._query())
        bad = score_candidate_prefetch(infinity_war, self._query())
        # Similar franchise prefix must not beat the true candidate...
        self.assertLess(bad.total, good.total)
        # ...nor reach the early-exit bar on prefetch evidence alone.
        self.assertLess(bad.total, 0.85)

    def test_unrelated_movie_never_outranks_or_exits_early(self):
        unrelated = wp_candidate(
            "https://www.f2medi.top/555/some-other-movie/",
            "post",
            "دانلود فیلم کاملا متفاوت Another Movie 2019",
        )
        good = score_candidate_prefetch(self._endgame_candidate(), self._query())
        bad = score_candidate_prefetch(unrelated, self._query())
        # Weak fuzzy overlap may pass the loose prefetch bar, but it must
        # rank far below the true candidate and never trigger early exit.
        self.assertLess(bad.total, good.total)
        self.assertLess(bad.total, 0.85)


class TestYearMatching(unittest.TestCase):
    def _score_with(self, wp_title, query_year=1994):
        query = MatchQuery(
            title="The Shawshank Redemption", item_type="movie", year=query_year
        )
        cand = wp_candidate("https://www.f2medi.top/3010/x/", "post", wp_title)
        return score_candidate_prefetch(cand, query)

    def test_exact_year(self):
        self.assertEqual(self._score_with(SHAWSHANK_WP_TITLE).year_match, 1.0)

    def test_off_by_one_year_half_credit(self):
        title = SHAWSHANK_WP_TITLE.replace("1994", "1995")
        self.assertEqual(self._score_with(title).year_match, 0.5)

    def test_wrong_year_no_credit(self):
        title = SHAWSHANK_WP_TITLE.replace("1994", "2003")
        self.assertEqual(self._score_with(title).year_match, 0.0)

    def test_missing_year_neutral(self):
        # No year on the WP title -> no year evidence at all.
        self.assertEqual(self._score_with("دانلود فیلم The Shawshank Redemption").year_match, 0.0)


class TestInvalidResultRejection(unittest.TestCase):
    def test_unrelated_title_rejected(self):
        query = MatchQuery(title="Avengers: Infinity War", item_type="movie")
        cand = wp_candidate(
            "https://www.f2medi.top/555/some-other-movie/",
            "post",
            "دانلود فیلم کاملا متفاوت Another Movie 2019",
        )
        score = score_candidate_prefetch(cand, query)
        self.assertFalse(passes_prefetch_gates(score))

    def test_search_hit_alone_is_not_enough(self):
        # A search hit with a mismatched subtype must not pass on URL
        # shape alone when the title is unrelated either.
        cand = SearchCandidate(
            url="https://www.f2medi.top/999/qqq-zzz/", method="search"
        )
        cand.subtype = None
        cand.wp_title = ""
        score = score_candidate_prefetch(cand, MatchQuery(title="Ted Lasso", item_type="movie"))
        self.assertFalse(passes_prefetch_gates(score))


if __name__ == "__main__":
    unittest.main()
