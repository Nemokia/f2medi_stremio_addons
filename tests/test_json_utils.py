"""Unit tests: BOM-tolerant JSON parsing (WordPress responses carry a BOM)."""

import unittest

from httpclient.json_utils import parse_json_bytes, parse_json_response, parse_json_text


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content


class TestBomHandling(unittest.TestCase):
    def test_utf8_bom_stripped(self):
        # Live-verified: f2medi.top wp-json payloads start with EF BB BF.
        raw = b'\xef\xbb\xbf[{"id": 9197, "subtype": "series"}]'
        data = parse_json_bytes(raw)
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["id"], 9197)

    def test_bom_on_object_payload(self):
        raw = '\ufeff{"name": "Film2Media"}'.encode("utf-8")
        self.assertEqual(parse_json_bytes(raw)["name"], "Film2Media")

    def test_plain_json_untouched(self):
        self.assertEqual(parse_json_bytes(b'[1, 2]'), [1, 2])

    def test_empty_body(self):
        self.assertIsNone(parse_json_bytes(b""))
        self.assertIsNone(parse_json_text("   "))

    def test_invalid_json_returns_none_not_raise(self):
        self.assertIsNone(parse_json_text("<html>not json</html>"))
        self.assertIsNone(parse_json_text('{"truncated": '))


class TestParseJsonResponse(unittest.TestCase):
    def test_response_with_bom(self):
        resp = FakeResponse('\ufeff{"url": "x"}'.encode())
        self.assertEqual(parse_json_response(resp)["url"], "x")

    def test_non_response_object(self):
        self.assertIsNone(parse_json_response(None))
        self.assertIsNone(parse_json_response(42))


if __name__ == "__main__":
    unittest.main()
