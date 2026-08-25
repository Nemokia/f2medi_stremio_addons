"""Unit tests: HTTP client retry policy and timeout handling."""

import unittest
from unittest.mock import patch

import requests

from httpclient.client import HttpClient, HttpClientConfig, HttpError


class FakeResponse:
    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.content = b"ok"


def client(max_retries=3, backoff=0.01):
    return HttpClient(
        HttpClientConfig(
            max_retries=max_retries,
            backoff_factor=backoff,
            verify_ssl=True,
        )
    )


class TestRetryPolicy(unittest.TestCase):
    @patch.object(requests.Session, "get")
    def test_success_first_try(self, mock_get):
        mock_get.return_value = FakeResponse(200)
        with client() as http:
            resp = http.get("https://www.f2medi.top/x")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_get.call_count, 1)

    @patch("httpclient.client.time.sleep")
    @patch.object(requests.Session, "get")
    def test_500_retried_then_succeeds(self, mock_get, mock_sleep):
        mock_get.side_effect = [FakeResponse(500), FakeResponse(200)]
        with client() as http:
            resp = http.get("https://www.f2medi.top/x")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_get.call_count, 2)

    @patch("httpclient.client.time.sleep")
    @patch.object(requests.Session, "get")
    def test_429_retries_honor_retry_after_header(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            FakeResponse(429, headers={"Retry-After": "7"}),
            FakeResponse(200),
        ]
        with client() as http:
            http.get("https://www.f2medi.top/x")
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(7.0)

    def test_404_never_retried(self):
        with patch.object(requests.Session, "get") as mock_get:
            mock_get.return_value = FakeResponse(404)
            with client() as http:
                resp = http.get("https://www.f2medi.top/missing")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(mock_get.call_count, 1)

    def test_403_never_retried(self):
        with patch.object(requests.Session, "get") as mock_get:
            mock_get.return_value = FakeResponse(403)
            with client() as http:
                resp = http.get("https://www.f2medi.top/denied")
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(resp.status_code, 403)

    def test_400_never_retried(self):
        with patch.object(requests.Session, "get") as mock_get:
            mock_get.return_value = FakeResponse(400)
            with client() as http:
                http.get("https://www.f2medi.top/bad")
        self.assertEqual(mock_get.call_count, 1)


class TestNetworkErrors(unittest.TestCase):
    @patch("httpclient.client.time.sleep")
    @patch.object(requests.Session, "get")
    def test_timeout_exhausts_retries_and_raises(self, mock_get, mock_sleep):
        mock_get.side_effect = requests.exceptions.Timeout("timed out")
        with client(max_retries=3) as http:
            with self.assertRaises(HttpError):
                http.get("https://www.f2medi.top/slow")
        self.assertEqual(mock_get.call_count, 3)

    @patch("httpclient.client.time.sleep")
    @patch.object(requests.Session, "get")
    def test_connection_error_recovers_midway(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            requests.exceptions.ConnectionError("reset"),
            FakeResponse(200),
        ]
        with client() as http:
            resp = http.get("https://www.f2medi.top/x")
        self.assertEqual(resp.status_code, 200)

    @patch.object(requests.Session, "get")
    def test_unexpected_exception_propagates_immediately(self, mock_get):
        # Programming errors must not be swallowed by the retry loop.
        mock_get.side_effect = ValueError("bad url build")
        with client() as http:
            with self.assertRaises(ValueError):
                http.get("https://www.f2medi.top/x")


if __name__ == "__main__":
    unittest.main()
