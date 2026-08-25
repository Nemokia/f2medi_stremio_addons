"""Unit tests: URL policy — allowlist, structure regexes, profile detection."""

import unittest

from resolvers.url_policy import (
    is_allowed_url,
    is_profile_or_login_url,
    normalize_candidate_url,
    safe_fetch_url,
    url_path_kind,
)


class TestNormalizeCandidateUrl(unittest.TestCase):
    def test_relative_resolved_against_base(self):
        self.assertEqual(
            normalize_candidate_url("/3010/foo/"),
            "https://www.f2medi.top/3010/foo/",
        )

    def test_fragment_stripped(self):
        url = normalize_candidate_url("https://www.f2medi.top/series/x/#comments")
        self.assertEqual(url, "https://www.f2medi.top/series/x/")

    def test_rejects_javascript_and_data_schemes(self):
        self.assertIsNone(normalize_candidate_url("javascript:alert(1)"))
        self.assertIsNone(normalize_candidate_url("data:text/html,x"))

    def test_rejects_embedded_credentials(self):
        self.assertIsNone(
            normalize_candidate_url("https://user:pass@f2medi.top/1/x/")
        )

    def test_rejects_empty(self):
        self.assertIsNone(normalize_candidate_url(""))
        self.assertIsNone(normalize_candidate_url(None))


class TestAllowlist(unittest.TestCase):
    def test_allowed_hosts(self):
        self.assertTrue(is_allowed_url("https://f2medi.top/x"))
        self.assertTrue(is_allowed_url("https://WWW.F2MEDI.TOP/x"))

    def test_external_hosts_blocked(self):
        # SSRF guard: results from search engines may point anywhere.
        for host in (
            "https://evil.example.com/1/a/",
            "https://f2medi.top.evil.example.com/1/a/",
            "https://192.168.0.1/secret",
            "file:///etc/passwd",
        ):
            self.assertFalse(is_allowed_url(host), host)

    def test_safe_fetch_gate(self):
        self.assertIsNone(safe_fetch_url("https://evil.example.com/1/a/"))
        self.assertIsNotNone(safe_fetch_url("https://www.f2medi.top/1/a/"))


class TestUrlStructure(unittest.TestCase):
    def test_movie_url_shape(self):
        self.assertEqual(
            url_path_kind("https://www.f2medi.top/3010/the-shawshank-redemption-1994-farsi-dubbed/"),
            "movie",
        )
        # Missing numeric prefix -> not a movie URL.
        self.assertIsNone(
            url_path_kind("https://www.f2medi.top/the-shawshank-redemption/")
        )

    def test_series_url_shape(self):
        self.assertEqual(
            url_path_kind("https://www.f2medi.top/series/zted-lasso-series/"),
            "series",
        )
        self.assertEqual(
            url_path_kind("https://www.f2medi.top/series/marasli"),
            "series",
        )

    def test_non_content_paths(self):
        self.assertIsNone(url_path_kind("https://www.f2medi.top/wp-json/wp/v2/search"))
        self.assertIsNone(url_path_kind("https://www.f2medi.top/profile/"))


class TestProfileDetection(unittest.TestCase):
    def test_profile_page_detected(self):
        self.assertTrue(is_profile_or_login_url("https://www.f2medi.top/profile/"))
        self.assertTrue(is_profile_or_login_url("https://www.f2medi.top/login"))

    def test_content_pages_pass(self):
        self.assertFalse(is_profile_or_login_url("https://www.f2medi.top/series/marasli/"))
        self.assertFalse(is_profile_or_login_url("https://www.f2medi.top/3010/foo/"))


if __name__ == "__main__":
    unittest.main()
