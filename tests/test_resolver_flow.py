"""Unit tests: resolver orchestration — fallback order, dedupe, budget, cache.

All HTTP and discovery stages are mocked; no test in this module touches
the network.
"""

import unittest
from unittest.mock import patch

from resolvers import F2MediaResolver
from resolvers.models import SearchCandidate


MOVIE_HTML = """<html><head><title>دانلود فیلم The Shawshank Redemption 1994</title></head>
<body><h1 class="entry-title">The Shawshank Redemption 1994</h1>
<div class="download-list hardsub"><ul>
<li><span class="text" dir="ltr">WEB-DL 1080p</span>
<a class="btn-download" href="https://dl.example/f.mkv">دانلود</a></li></ul></div>
<!-- padding -->""" + "x" * 400 + "</body></html>"

SERIES_HTML = """<html><head><title>دانلود سریال Ted Lasso</title></head>
<body><h1 class="entry-title">Ted Lasso 2020</h1>
<div class="download-season"><button data-bs-target="#b0">فصل اول</button></div>
<div id="b0"><ul><li class="bg-body"><span class="text" dir="ltr">1080p</span>
<div class="series-downloaditems"><div class="d-flex">
<a href="https://www.f2medi.top/series/zted-lasso-series/">p</a>
<a href="https://dl.example/e01.mkv">قسمت 01</a></div></div></li></ul></div>
<!-- padding -->""" + "y" * 400 + "</body></html>"


class FakeResponse:
    def __init__(self, html):
        self.status_code = 200
        self.text = html
        self.content = html.encode()
        self.url = "https://www.f2medi.top/3010/x/"


class CountingHttp:
    """Fake HttpClient returning one canned page per distinct URL."""

    def __init__(self, html_by_url=None, default_html=MOVIE_HTML):
        self.html_by_url = html_by_url or {}
        self.default_html = default_html
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        return FakeResponse(self.html_by_url.get(url, self.default_html))


def wp_candidate(url, wp_title, subtype="post"):
    return SearchCandidate(
        url=url, method="wordpress", subtype=subtype, wp_title=wp_title
    )


SHAWSHANK_WP_TITLE = "دانلود فیلم The Shawshank Redemption 1994"


def make_resolver(http):
    return F2MediaResolver(http=http, cache=None)


class ResolverFlowTestCase(unittest.TestCase):
    def setUp(self):
        # Fallback stages default to empty in every flow test so nothing
        # here can reach the network; individual tests override them.
        patcher_direct = patch(
            "resolvers.f2medi_resolver.direct_candidates", return_value=[]
        )
        patcher_search = patch(
            "resolvers.f2medi_resolver.search_fallback_candidates",
            return_value=[],
        )
        self.mock_direct = patcher_direct.start()
        self.mock_search = patcher_search.start()
        self.addCleanup(patcher_direct.stop)
        self.addCleanup(patcher_search.stop)

    def make(self, http):
        self.resolver = make_resolver(http)
        return self.resolver


class TestFallbackOrder(ResolverFlowTestCase):
    @patch.object(F2MediaResolver, "_try_candidate", return_value=None)
    def test_search_stage_runs_after_wordpress_fails(self, try_cand):
        """WP candidates exist but validation rejects them -> search runs."""
        http = CountingHttp(default_html="<html>" + "q" * 600 + "</html>")
        resolver = self.make(http)
        wp_cands = [wp_candidate("https://www.f2medi.top/3010/wrong/", SHAWSHANK_WP_TITLE)]

        with patch.object(resolver.wordpress, "_search_once", return_value=wp_cands):
            result = resolver.resolve(
                title="The Shawshank Redemption", item_type="movie", year=1994
            )

        try_cand.assert_called()          # WP stage attempted validation
        self.mock_search.assert_called_once()  # then fell through to search
        self.assertFalse(result.found)

    def test_direct_stage_runs_for_series_when_wp_empty(self):
        http = CountingHttp()
        resolver = self.make(http)
        self.mock_direct.return_value = [
            SearchCandidate(url="https://www.f2medi.top/series/x/", method="direct")
        ]
        with patch.object(resolver.wordpress, "_search_once", return_value=[]):
            resolver.resolve(title="Some Show", item_type="series")
        self.mock_direct.assert_called_once()

    def test_method_records_discovery_source(self):
        http = CountingHttp()
        resolver = self.make(http)
        wp_cands = [
            wp_candidate("https://www.f2medi.top/3010/x/", SHAWSHANK_WP_TITLE)
        ]
        with patch.object(resolver.wordpress, "_search_once", return_value=wp_cands):
            result = resolver.resolve(
                title="The Shawshank Redemption", item_type="movie", year=1994
            )
        self.assertTrue(result.found)
        self.assertEqual(result.method, "wordpress")


class TestDeduplication(ResolverFlowTestCase):
    def test_duplicate_wp_results_fetched_once(self):
        http = CountingHttp()
        resolver = self.make(http)
        dup = wp_candidate("https://www.f2medi.top/3010/x/", SHAWSHANK_WP_TITLE)

        with patch.object(resolver.wordpress, "_search_once", return_value=[dup, dup, dup]):
            result = resolver.resolve(
                title="The Shawshank Redemption", item_type="movie", year=1994
            )

        self.assertTrue(result.found)
        self.assertEqual(len(http.calls), 1)


class TestFetchBudget(ResolverFlowTestCase):
    def test_candidate_fetch_count_is_capped(self):
        cands = [
            wp_candidate(f"https://www.f2medi.top/{1000+i}/x/", SHAWSHANK_WP_TITLE)
            for i in range(10)
        ]
        http = CountingHttp(default_html="<html>" + "z" * 600 + "</html>")
        resolver = self.make(http)

        with patch.object(resolver.wordpress, "_search_once", return_value=cands):
            result = resolver.resolve(
                title="The Shawshank Redemption", item_type="movie", year=1994
            )

        # _MAX_CANDIDATES_FETCH bounds fetches per stage; fallback stages
        # are mocked empty here so nothing else is fetched.
        self.assertLessEqual(len(http.calls), 4)
        self.assertFalse(result.found)


class TestCacheBehavior(ResolverFlowTestCase):
    def test_second_resolve_uses_cache_without_new_requests(self):
        http = CountingHttp()
        resolver = self.make(http)
        wp_cands = [wp_candidate("https://www.f2medi.top/3010/x/", SHAWSHANK_WP_TITLE)]

        with patch.object(resolver.wordpress, "_search_once", return_value=wp_cands) as disc:
            first = resolver.resolve(
                title="The Shawshank Redemption", item_type="movie", year=1994
            )
        self.assertTrue(first.found)

        n_after_first = len(http.calls)
        with patch.object(resolver.wordpress, "_search_once") as disc2:
            second = resolver.resolve(
                title="The Shawshank Redemption", item_type="movie", year=1994
            )

        self.assertEqual(second.url, first.url)
        self.assertEqual(len(http.calls), n_after_first)  # zero new requests
        disc2.assert_not_called()                         # zero new discovery

    def test_negative_result_is_cached_briefly(self):
        http = CountingHttp(default_html="<html>" + "n" * 700 + "</html>")
        resolver = self.make(http)

        with patch.object(resolver.wordpress, "_search_once", return_value=[]):
            first = resolver.resolve(
                title="The Shawshank Redemption", item_type="movie", year=1994
            )
        self.assertFalse(first.found)

        with patch.object(resolver.wordpress, "_search_once") as disc:
            second = resolver.resolve(
                title="The Shawshank Redemption", item_type="movie", year=1994
            )
        self.assertFalse(second.found)
        disc.assert_not_called()


ENDGAME_WP_TITLE = (
    "دانلود دوبله فارسی فیلم انتقام جویان پایان بازی Avengers Endgame 2019"
)


def endgame_candidate(url="https://www.f2medi.top/175/avengers-endgame-2019/"):
    return SearchCandidate(
        url=url,
        method="wordpress",
        subtype="post",
        wp_id=175,
        wp_title=ENDGAME_WP_TITLE,
    )


class TestQueryVariantFlow(ResolverFlowTestCase):
    """Movie discovery must walk WP query variants with early success."""

    def test_second_variant_queried_when_first_returns_nothing(self):
        http = CountingHttp()
        resolver = self.make(http)

        with patch.object(
            resolver.wordpress,
            "_search_once",
            side_effect=[[], [endgame_candidate()]],
        ) as search:
            result = resolver.resolve(
                title="Avengers: Endgame", item_type="movie",
                year=2019, imdb_id="tt4154796",
            )

        self.assertTrue(result.found)
        self.assertEqual(result.method, "wordpress")
        self.assertEqual(search.call_count, 2)  # variant 1 empty -> variant 2
        first_args, first_kwargs = search.call_args_list[0]
        self.assertEqual(first_kwargs.get("subtype"), "post")
        second_args, second_kwargs = search.call_args_list[1]
        self.assertEqual(second_kwargs.get("subtype"), "post")

    def test_success_on_first_query_skips_remaining_queries(self):
        http = CountingHttp()
        resolver = self.make(http)

        with patch.object(
            resolver.wordpress,
            "_search_once",
            return_value=[endgame_candidate()],
        ) as search:
            result = resolver.resolve(
                title="Avengers: Endgame", item_type="movie", year=2019
            )

        self.assertTrue(result.found)
        search.assert_called_once()  # no pointless follow-up queries

    def test_untyped_safety_net_only_after_all_variants_empty(self):
        http = CountingHttp()
        resolver = self.make(http)

        with patch.object(
            resolver.wordpress,
            "_search_once",
            side_effect=[[], [], [], []],
        ) as search:
            result = resolver.resolve(
                title="Avengers: Endgame", item_type="movie", year=2019
            )

        self.assertFalse(result.found)
        # 3 typed variants (title, stripped, stripped+year) + 1 untyped net.
        self.assertEqual(search.call_count, 4)
        last_args, last_kwargs = search.call_args_list[-1]
        self.assertIsNone(last_kwargs.get("subtype"))


class TestCandidatePoolDedup(ResolverFlowTestCase):
    def test_same_wp_id_across_queries_fetched_once(self):
        http = CountingHttp(default_html="<html>" + "q" * 600 + "</html>")
        resolver = self.make(http)

        batch_1 = [endgame_candidate("https://www.f2medi.top/175/a/")]
        batch_2 = [
            endgame_candidate("https://www.f2medi.top/175/b/"),  # same id 175
            wp_candidate("https://www.f2medi.top/176/c/", ENDGAME_WP_TITLE),
        ]

        with patch.object(
            resolver.wordpress,
            "_search_once",
            side_effect=[batch_1, batch_2],
        ):
            resolver.resolve(title="Avengers: Endgame", item_type="movie")

        page_urls = [
            c for c in http.calls if "/wp-json/" not in c
        ]
        self.assertEqual(len(page_urls), 2)  # /175/a/ and /176/c/, not /175/b/

    def test_duplicate_wp_results_fetched_once_by_id_not_url(self):
        http = CountingHttp()
        resolver = self.make(http)
        variants_of_same_page = [
            endgame_candidate("https://www.f2medi.top/175/a/"),
            endgame_candidate("https://www.f2medi.top/175/b/"),
        ]

        with patch.object(
            resolver.wordpress,
            "_search_once",
            return_value=variants_of_same_page,
        ):
            result = resolver.resolve(
                title="Avengers: Endgame", item_type="movie"
            )

        self.assertTrue(result.found)
        page_fetches = [c for c in http.calls if "/wp-json/" not in c]
        self.assertEqual(len(page_fetches), 1)


if __name__ == "__main__":
    unittest.main()
