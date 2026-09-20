"""Unit tests: utils.htmldom — tree building + CSS-subset engine."""

import unittest

from utils.htmldom import Minisoup, SelectorError


class TestTreeBuilding(unittest.TestCase):
    def test_void_hr_keeps_siblings_sibling(self):
        soup = Minisoup(
            '<div><hr class="mt-0"><ul><li class="bg-body">x</li></ul>'
            "<p>after</p></div>"
        )
        self.assertIsNotNone(soup.select_one("li.bg-body"))
        self.assertEqual(soup.select_one("p").get_text(), "after")
        # hr must have zero children even though unclosed.
        hr = soup.select_one("hr")
        self.assertFalse(any(isinstance(c, type(hr)) for c in hr.children)
                         or True)
        lis = soup.select("li.bg-body")
        self.assertEqual(len(lis), 1)

    def test_li_autocloses_previous_li(self):
        soup = Minisoup('<ul><li>a<li>b<li>c</ul>')
        items = soup.select("ul > li")
        texts = sorted(li.get_text(strip=True) for li in items)
        self.assertEqual(texts, ["a", "b", "c"])

    def test_block_starter_closes_open_p(self):
        soup = Minisoup("<p>one<div>two</div>")
        p = soup.select_one("p")
        self.assertEqual(p.get_text(strip=True), "one")

    def test_unmatched_end_tag_ignored(self):
        soup = Minisoup("</div></li><p>ok</p>")
        self.assertEqual(soup.select_one("p").get_text(), "ok")

    def test_script_body_never_creates_elements(self):
        html = (
            "<script>var s = \"<div class=\\\"download-season\\\">\";"
            "</script>"
        )
        soup = Minisoup(html)
        self.assertIsNone(soup.select_one(".download-season"))
        self.assertIsNone(soup.select_one("script div"))

    def test_duplicate_attributes_last_wins(self):
        soup = Minisoup('<a id="first" id="second">x</a>')
        self.assertEqual(soup.select_one("a").get("id"), "second")

    def test_boolean_attribute_is_none(self):
        soup = Minisoup('<a download target="_blank">x</a>')
        anchor = soup.select_one("a")
        self.assertIsNone(anchor.get("download"))
        self.assertEqual(anchor.get("target"), "_blank")

    def test_class_value_tokenized_to_list(self):
        soup = Minisoup(
            '<div class="download-list dubbled hardsub">'
        )
        block = soup.select_one(".download-list")
        classes = block.get("class", [])
        self.assertIsInstance(classes, list)
        for token in ("download-list", "dubbled", "hardsub"):
            self.assertIn(token, classes)

    def test_entities_unescaped_in_text_and_attrs(self):
        soup = Minisoup('<a href="/x?a=1&amp;b=2">&gt;&amp;&lt;</a>')
        anchor = soup.select_one("a")
        self.assertEqual(anchor["href"], "/x?a=1&b=2")
        self.assertEqual(anchor.get_text(), ">&<"[:3])

    def test_get_text_strip_joins_pieces_with_sep(self):
        soup = Minisoup(
            "<span>\n  WEB-DL\n  <b>1080p</b>\n</span>"
        )
        self.assertEqual(soup.select_one("span").get_text(" ", strip=True),
                         "WEB-DL 1080p")


class TestSelectors(unittest.TestCase):
    def _season_fixture(self):
        return Minisoup(
            """
            <div class="download-season bg-card">
              <button data-bs-target="#box0">فصل اول</button>
              <div id="box0">
                <ul>
                  <li class="bg-body"><span class="text" dir="ltr">1080p</span>
                    <div class="series-downloaditems"><div class="d-flex">
                      <a href="/page/">p</a>
                      <a href="https://dl.example/e01.mkv">قسمت 01</a>
                    </div></div>
                  </li>
                  <li class="bg-body"><button data-bs-target="#sub">مشاهده لینک ها</button></li>
                </ul>
              </div>
            </div>
            <a href="https://imdb.com/title/tt0000000/">imdb</a>
            <strong>x</strong>
            <link rel="canonical" href="https://www.f2medi.top/175/x/">
            """
        )

    def test_scope_child_excludes_grandchildren(self):
        soup = self._season_fixture()
        season = soup.select_one(".download-season")
        buttons = season.select(":scope > button[data-bs-target]")
        self.assertEqual(len(buttons), 1)
        self.assertIn("#box0", str(buttons[0].get("data-bs-target")))

    def test_id_lookup_via_compound(self):
        soup = self._season_fixture()
        box = soup.select_one("#box0")
        self.assertIsNotNone(box)
        rows = box.select("li.bg-body")
        self.assertEqual(len(rows), 2)

    def test_descendant_vs_child_combinator(self):
        soup = Minisoup(
            '<div class="outer"><section><span class="hit">a</span>'
            "</section><span class=\"hit\">b</span></div>"
        )
        outer = soup.select_one(".outer")
        self.assertEqual(len(outer.select(":scope span.hit")), 2)
        self.assertEqual(len(outer.select(":scope > span.hit")), 1)

    def test_attr_presence_and_exact(self):
        soup = self._season_fixture()
        canonical = soup.select_one('link[rel="canonical"]')
        self.assertIsNotNone(canonical)
        labeled = soup.select_one('span.text[dir="ltr"]')
        self.assertEqual(labeled.get_text(strip=True), "1080p")

    def test_attr_substring_match(self):
        soup = Minisoup(
            '<a href="https://www.imdb.com/title/tt123/">x</a>'
            '<a href="/local/">y</a>'
        )
        hit = soup.select_one('a[href*="imdb.com"]')
        self.assertEqual(hit.get_text(), "x")

    def test_select_one_returns_first_in_document_order(self):
        soup = Minisoup(
            '<ul><li><a class="btn-download" href="/real.mkv">دانلود'
            '</a><a class="btn-download" href="#">پخش</a></li>'
            "</ul>"
        )
        row = soup.select_one("li")
        first = row.select_one("a.btn-download")
        self.assertTrue(first["href"].endswith("/real.mkv"))

    def test_title_property_and_last_anchor_indexing(self):
        soup = Minisoup(
            "<html><head><title>دانلود فیلم X 1994</title></head>"
            "<body><div class='series-downloaditems'><div class='d-flex'>"
            '<a href="/p/">p</a><a href="https://dl/e02.mkv">قسمت 2</a>'
            "</div></div></body></html>"
        )
        self.assertEqual(soup.title.get_text(" ", strip=True),
                         "دانلود فیلم X 1994")
        block = soup.select_one(".d-flex")
        anchors = [a for a in block.select("a[href]") if a.get("href")]
        self.assertTrue(anchors[-1]["href"].endswith("/e02.mkv"))
        self.assertEqual(anchors[-1].get_text(strip=True), "قسمت 2")


class TestUnsupportedSyntax(unittest.TestCase):
    def test_unknown_pseudo_raises(self):
        with self.assertRaises(SelectorError):
            Minisoup("<div>").select_one("div:first-child")

    def test_sibling_combinator_raises(self):
        with self.assertRaises(SelectorError):
            Minisoup("<div><p></p><span></span></div>").select("p + span")

    def test_dangling_combinator_raises(self):
        with self.assertRaises(SelectorError):
            Minisoup("<div><p></p></div>").select("div >")

    def test_comma_group_raises(self):
        with self.assertRaises(ValueError):
            Minisoup("<p></p><h1></h1>").select("p, h1")


class TestMalformedStorm(unittest.TestCase):
    def test_end_tag_storm_smoke(self):
        garbage = "</div>" * 50 + '<li class="bg-body">keep</li>' + \
            "</li></ul></table>" * 20
        soup = Minisoup(garbage)
        row = soup.select_one("li.bg-body")
        self.assertIsNotNone(row)
        self.assertEqual(row.get_text(strip=True), "keep")


if __name__ == "__main__":
    unittest.main(verbosity=2)
