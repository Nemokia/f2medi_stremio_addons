"""Unit tests: page validation — login walls, Cloudflare, structure, canonical."""

import unittest

from resolvers.validator import (
    extract_canonical_url,
    looks_like_cloudflare,
    validate_content_page,
)
from bs4 import BeautifulSoup


def fake_response(html, url="https://www.f2medi.top/x/", status=200):
    class R:
        pass

    r = R()
    r.status_code = status
    r.text = html
    r.url = url
    return r


MOVIE_HTML = """<html><head><title>دانلود فیلم رستگاری در شاوشنک The Shawshank Redemption 1994</title>
<link rel="canonical" href="https://www.f2medi.top/3010/the-shawshank-redemption-1994-farsi-dubbed/"></head>
<body><h1 class="entry-title">The Shawshank Redemption 1994</h1>
<div class="download-list dubbled"><ul>
<li><span class="text" dir="ltr">WEB-DL 1080p</span><a class="btn-download" href="https://dl.example/f1.mkv">دانلود</a></li>
</ul></div>
<div class="download-list hardsub"><ul>
<li><span class="text" dir="ltr">WEB-DL 720p</span><a class="btn-download" href="https://dl.example/f2.mkv">دانلود</a></li>
</ul></div></body></html>"""

SERIES_HTML = """<html><head><title>دانلود سریال تد لاسو Ted Lasso</title>
<link rel="canonical" href="https://www.f2medi.top/series/zted-lasso-series/"></head>
<body><h1 class="entry-title">Ted Lasso 2020</h1>
<div class="download-list hardsub"><ul><li><span class="text" dir="ltr">1080p</span></li></ul></div>
<div class="download-season"><button data-bs-target="#season-dlbox0">فصل اول</button></div>
<div id="season-dlbox0" class="collapse"><ul>
<li class="bg-body"><span class="text" dir="ltr">WEB-DL 1080p</span>
<div class="series-downloaditems"><div class="d-flex">
<a href="https://www.f2medi.top/series/zted-lasso-series/">page</a><a href="#">#</a>
<a href="https://dl.example/e01.mkv">قسمت 01</a></div></div></li>
</ul></div></body></html>"""

PROFILE_HTML = (
    "<html><head><title>پروفایل کاربری</title></head>"
    "<body><form><input type='password'></form>" + "x" * 600 + "</body></html>"
)

CLOUDFLARE_HTML = (
    "<html><head><title>Just a moment...</title></head><body>"
    "<script src='/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1'>"
    "</script></body></html>"
)


class TestMoviePageValidation(unittest.TestCase):
    def test_valid_movie_accepted(self):
        result = validate_content_page(
            fake_response(MOVIE_HTML), item_type="movie"
        )
        self.assertTrue(result.ok)
        self.assertIn("Shawshank", result.title)
        self.assertEqual(result.year, 1994)

    def test_series_structure_rejected_for_movie_query(self):
        # A series page must not pass as a movie page.
        result = validate_content_page(
            fake_response(SERIES_HTML), item_type="movie"
        )
        self.assertFalse(result.ok)


class TestSeriesPageValidation(unittest.TestCase):
    def test_valid_series_accepted(self):
        result = validate_content_page(
            fake_response(SERIES_HTML), item_type="series"
        )
        self.assertTrue(result.ok)
        self.assertIn("Ted Lasso", result.title)

    def test_movie_page_rejected_for_series_query(self):
        result = validate_content_page(
            fake_response(MOVIE_HTML), item_type="series"
        )
        self.assertFalse(result.ok)


class TestRejections(unittest.TestCase):
    def test_login_profile_title_rejected(self):
        for item in ("movie", "series"):
            result = validate_content_page(
                fake_response(PROFILE_HTML, url="https://www.f2medi.top/profile/"),
                item_type=item,
            )
            self.assertFalse(result.ok)

    def test_profile_redirect_landing_rejected(self):
        # Site soft-fails unknown URLs by 301 -> /profile/.
        result = validate_content_page(
            fake_response(PROFILE_HTML, url="https://www.f2medi.top/profile/"),
            item_type="movie",
        )
        self.assertFalse(result.ok)

    def test_cloudflare_challenge_rejected(self):
        result = validate_content_page(
            fake_response(CLOUDFLARE_HTML), item_type="movie"
        )
        self.assertFalse(result.ok)
        self.assertIn("cloudflare", result.reason)

    def test_404_rejected(self):
        result = validate_content_page(
            fake_response(MOVIE_HTML, status=404), item_type="movie"
        )
        self.assertFalse(result.ok)

    def test_tiny_body_rejected(self):
        result = validate_content_page(fake_response("<html></html>"), item_type="movie")
        self.assertFalse(result.ok)

    def test_unknown_item_type_rejected(self):
        result = validate_content_page(fake_response(MOVIE_HTML), item_type="")
        self.assertFalse(result.ok)


class TestCloudflareDetection(unittest.TestCase):
    def test_markers(self):
        self.assertTrue(looks_like_cloudflare("Please wait... cf-chl-bypass"))
        self.assertTrue(looks_like_cloudflare("Attention Required!"))
        self.assertFalse(looks_like_cloudflare(MOVIE_HTML))
        self.assertFalse(looks_like_cloudflare(""))


class TestCanonicalExtraction(unittest.TestCase):
    def test_absolute_canonical(self):
        soup = BeautifulSoup(MOVIE_HTML, "html.parser")
        self.assertEqual(
            extract_canonical_url(soup),
            "https://www.f2medi.top/3010/the-shawshank-redemption-1994-farsi-dubbed/",
        )

    def test_relative_canonical_resolved(self):
        html = '<html><head><link rel="canonical" href="/series/foo/"></head></html>'
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(extract_canonical_url(soup), "https://www.f2medi.top/series/foo/")

    def test_missing_canonical(self):
        soup = BeautifulSoup("<html><head></head></html>", "html.parser")
        self.assertIsNone(extract_canonical_url(soup))


if __name__ == "__main__":
    unittest.main()
