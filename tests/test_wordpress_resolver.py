"""Unit tests: WordPress REST discovery — subtype mapping, BOM, variants."""

import unittest
from unittest.mock import patch

from resolvers.wordpress_resolver import WordPressResolver, wp_subtype_for


class FakeWpResponse:
    def __init__(self, payload: bytes):
        self.status_code = 200
        self.content = payload


class CapturingHttp:
    """Records every search request; replays queued payloads in order."""

    def __init__(self, payloads=None):
        self.payloads = list(payloads or [])
        self.requests: list[dict] = []

    def get(self, url, *, params=None, **kwargs):
        self.requests.append({"url": url, "params": dict(params or {})})
        payload = self.payloads.pop(0) if self.payloads else b"\xef\xbb\xbf[]"
        return FakeWpResponse(payload)


def wp_entry(wp_id, title, subtype="post"):
    import json

    item = {
        "id": wp_id,
        "title": title,
        "url": f"https://www.f2medi.top/{wp_id}/slug/",
        "type": subtype,
        "subtype": subtype,
    }
    # Live responses carry a UTF-8 BOM before the JSON array.
    return ("\ufeff" + json.dumps([item])).encode("utf-8")


class TestSubtypeMapping(unittest.TestCase):
    def test_movie_maps_to_post(self):
        self.assertEqual(wp_subtype_for("movie"), "post")

    def test_series_maps_to_series(self):
        self.assertEqual(wp_subtype_for("series"), "series")

    def test_unknown_type_untyped(self):
        self.assertIsNone(wp_subtype_for("other"))


class TestSearchRequests(unittest.TestCase):
    def test_movie_search_sends_subtype_post(self):
        http = CapturingHttp([wp_entry(3010, "دانلود فیلم The Shawshank Redemption 1994")])
        resolver = WordPressResolver(http)
        results = resolver.discover(
            "The Shawshank Redemption", item_type="movie"
        )
        self.assertEqual(len(results), 1)
        sent = http.requests[0]["params"]
        self.assertEqual(sent["search"], "The Shawshank Redemption")
        self.assertEqual(sent["subtype"], "post")

    def test_series_search_sends_subtype_series(self):
        http = CapturingHttp([wp_entry(9197, "دانلود سریال Ted Lasso", subtype="series")])
        resolver = WordPressResolver(http)
        results = resolver.discover("Ted Lasso", item_type="series")
        self.assertEqual(len(results), 1)
        self.assertEqual(http.requests[0]["params"]["subtype"], "series")

    def test_bom_payload_parsed_via_json_utils(self):
        # Live-verified wire format: UTF-8 BOM + JSON array.
        raw = '\ufeff[{"id": 175, "title": "Avengers Endgame 2019", ' \
              '"url": "https://www.f2medi.top/175/x/", "subtype": "post"}]'
        http = CapturingHttp([raw.encode("utf-8")])
        resolver = WordPressResolver(http)
        results = resolver.discover("Avengers Endgame", item_type="movie")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].wp_id, 175)
        self.assertEqual(results[0].subtype, "post")

    def test_duplicate_urls_within_one_response_dropped(self):
        import json

        duplicated = json.dumps([
            {"id": 175, "title": "a", "url": "https://www.f2medi.top/175/x/",
             "subtype": "post"},
            {"id": 175, "title": "a", "url": "https://www.f2medi.top/175/x/",
             "subtype": "post"},
        ])
        http = CapturingHttp([("\ufeff" + duplicated).encode()])
        resolver = WordPressResolver(http)
        self.assertEqual(len(resolver.discover("q", item_type="movie")), 1)

    def test_candidates_carry_method_wordpress(self):
        http = CapturingHttp([wp_entry(175, "Avengers Endgame 2019")])
        resolver = WordPressResolver(http)
        results = resolver.discover("Avengers Endgame", item_type="movie")
        self.assertEqual(results[0].method, "wordpress")


class TestQueryVariantDiscovery(unittest.TestCase):
    def setUp(self):
        self.http = CapturingHttp()
        self.resolver = WordPressResolver(self.http)

    def _queries_sent(self):
        return [r["params"]["search"] for r in self.http.requests]

    def test_variants_run_in_order_until_first_hit(self):
        # Query 1 ("Avengers: Endgame") -> []; query 2 -> hit.
        self.http.payloads = [
            b"\xef\xbb\xbf[]",
            wp_entry(175, "دانلود فیلم انتقام جویان Avengers Endgame 2019"),
        ]
        batches = self.resolver.iter_discover(
            "Avengers: Endgame", item_type="movie", year=2019
        )
        label, results = next(batches)
        batches.close()  # caller stops: no further queries may be sent

        # Hit on variant 2: the year variant must never be requested.
        self.assertEqual(
            self._queries_sent(),
            ["Avengers: Endgame", "Avengers Endgame"],
        )
        self.assertEqual(label, "wp-q2")
        self.assertEqual([r.wp_id for r in results], [175])

    def test_year_variant_tried_last(self):
        # All typed variants empty -> untyped safety net fires afterwards.
        self.http.payloads = [b"\xef\xbb\xbf[]"] * 4
        batches = list(
            self.resolver.iter_discover(
                "Avengers: Endgame", item_type="movie", year=2019
            )
        )
        self.assertEqual(self._queries_sent(), [
            "Avengers: Endgame",
            "Avengers Endgame",
            "Avengers Endgame 2019",
            "Avengers: Endgame",   # untyped net re-uses the original title
        ])
        self.assertEqual(len(batches), 0)

    def test_no_punctuation_title_single_typed_variant_plus_net(self):
        self.http.payloads = [b"\xef\xbb\xbf[]"] * 3
        list(self.resolver.iter_discover(
            "Ted Lasso", item_type="series", year=2020
        ))
        subtypes = [r["params"].get("subtype") for r in self.http.requests]
        self.assertEqual(subtypes, ["series", "series", None])
        self.assertEqual(self._queries_sent(), [
            "Ted Lasso", "Ted Lasso 2020", "Ted Lasso",
        ])

    def test_untyped_net_runs_once_after_all_typed_empty(self):
        self.http.payloads = [b"\xef\xbb\xbf[]"] * 3
        list(self.resolver.iter_discover("Avengers: Endgame",
                                         item_type="movie"))
        subtypes = [r["params"].get("subtype") for r in self.http.requests]
        self.assertEqual(subtypes, ["post", "post", None])
        self.assertEqual(self._queries_sent()[-1], "Avengers: Endgame")

    def test_discover_eager_wrapper_collects_all_batches(self):
        self.http.payloads = [
            wp_entry(175, "first"),
            wp_entry(176, "second"),
        ]
        results = self.resolver.discover(
            "Avengers: Endgame", item_type="movie", year=2019
        )
        # Eager wrapper runs every query variant and concatenates;
        # early-success stopping is enforced by F2MediaResolver.
        self.assertEqual([r.wp_id for r in results], [175, 176])


if __name__ == "__main__":
    unittest.main()
