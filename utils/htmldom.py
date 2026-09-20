"""Minimal HTML DOM + CSS-selector engine (stdlib only).

Replaces BeautifulSoup-in-"html.parser" mode for the exact API surface
this project consumes:

    Minisoup(html) / Minisoup(element)
    soup.select(sel) -> list[Element]     # document order
    soup.select_one(sel) -> Element|None  # first in document order
    soup.title                            # first <title> element or None
    el.get(name, default=None)
    el[name]                              # KeyError when missing
    el.get_text(" ", strip=True)
    el.select(sel) / el.select_one(sel)   # relative to this element
    el.name                               # lowercased tag name

Attribute conventions (mirroring bs4):
    * duplicate attributes collapse last-wins;
    * valueless attributes (``<a download>``) store ``None``;
    * ``class`` and ``rel`` values tokenize into ``list[str]``.

Supported selector grammar — deliberately small; unknown syntax raises
``ValueError`` instead of silently matching nothing:

    compound   = [":scope"] | tag | `*` | `#id` | `.class`
                 | `[attr]` | `[attr=v]` | `[attr*=v]`   (combinable)
    combinator = descendant (whitespace) | child (`>`)

Tree-building rules mirror bs4-over-html.parser: void elements never
nest children; ``li``/``p``/table cells auto-close on the usual start
tags; unmatched end tags are ignored; comments/doctype are dropped;
``script``/``style`` bodies stay one raw text node (html.parser already
runs their CDATA mode).
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Iterator, Optional


class SelectorError(ValueError):
    """Selector syntax outside the supported subset."""


VOID_ELEMENTS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)

# Start tags that implicitly close an open sibling of certain tags.
_IMPLICIT_CLOSE: dict[str, frozenset[str]] = {
    "li": frozenset({"li"}),
    "option": frozenset({"option"}),
    "tr": frozenset({"tr", "td", "th"}),
    "td": frozenset({"td", "th"}),
    "th": frozenset({"td", "th"}),
    "dd": frozenset({"dd", "dt"}),
    "dt": frozenset({"dd", "dt"}),
}

# Block-level starters that close an open <p>.
_BLOCK_STARTERS = frozenset(
    {
        "address", "article", "aside", "blockquote", "details", "div",
        "dl", "fieldset", "figcaption", "figure", "footer", "form",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr",
        "main", "menu", "nav", "ol", "pre", "section", "table", "ul",
    }
)

_TOKENIZED_ATTRS = frozenset({"class", "rel"})

_SCOPE = ":scope"


class TextNode:
    __slots__ = ("data",)

    def __init__(self, data: str) -> None:
        self.data = data


class Element:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(
        self,
        tag: str,
        attrs: dict[str, object],
        parent: Optional["Element"] = None,
    ) -> None:
        self.tag = tag.lower()
        self.attrs = attrs
        self.children: list["Element | TextNode"] = []
        self.parent = parent

    # -- basic API ------------------------------------------------------

    @property
    def name(self) -> str:
        return self.tag

    def get(self, name: str, default: object = None) -> object:
        return self.attrs.get(name, default)

    def __getitem__(self, name: str) -> object:
        try:
            return self.attrs[name]
        except KeyError:
            raise KeyError(f"no attribute named {name!r} on <{self.tag}>")

    def get_text(self, sep: str = " ", strip: bool = False) -> str:
        """bs4-compatible: join descendant text nodes with ``sep``.

        ``strip=True`` strips every individual string and drops pure-
        whitespace runs before joining (bs4's exact contract).
        """
        pieces: list[str] = []
        for node in self._iter():
            if isinstance(node, TextNode):
                value = node.data
                if strip:
                    value = value.strip()
                if value:
                    pieces.append(value)
        return sep.join(pieces)

    def _iter(self) -> Iterator["Element | TextNode"]:
        stack: list["Element | TextNode"] = list(reversed(self.children))
        while stack:
            node = stack.pop()
            yield node
            if isinstance(node, Element):
                stack.extend(reversed(node.children))

    # -- selection ------------------------------------------------------

    def select(self, selector: str) -> list["Element"]:
        parsed = compile_selector(selector)
        out: list[Element] = []
        for el in self.descendants():
            if _matches_chain(parsed, el, scope=self):
                out.append(el)
        return out

    def select_one(self, selector: str) -> Optional["Element"]:
        parsed = compile_selector(selector)
        for el in self.descendants():
            if _matches_chain(parsed, el, scope=self):
                return el
        return None

    def descendants(self) -> Iterator["Element"]:
        for node in self._iter():
            if isinstance(node, Element):
                yield node

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Element {self.tag!r}>"


class Document(Element):
    """Synthetic super-root; tag ``[document]`` can never be selected."""

    def __init__(self) -> None:
        super().__init__("[document]", {})

    @property
    def title(self) -> Optional[Element]:
        return self.select_one("title")


def _select_from_document(doc: Document, selector: str) -> list[Element]:
    return [
        el
        for el in doc.descendants()
        if _matches_chain(compile_selector(selector), el, scope=doc)
    ]


class Minisoup:
    """Facade over a parsed document (or a wrapped subtree element)."""

    def __init__(self, markup: str | Element) -> None:
        if isinstance(markup, Document):
            self.root = markup
        elif isinstance(markup, Element):
            wrapper = Document()
            markup.parent = wrapper
            wrapper.children.append(markup)
            self.root = wrapper
            self._wrapped = markup
        else:
            self.root = parse_document(markup)
            self._wrapped = None

    @property
    def title(self) -> Optional[Element]:
        if isinstance(self.root, Document):
            return self.root.title
        return self.root.select_one("title")

    def select(self, selector: str) -> list[Element]:
        if self._wrapped is None:
            return _select_from_document(self.root, selector)
        return self._wrapped.select(selector)

    def select_one(self, selector: str) -> Optional[Element]:
        if self._wrapped is None:
            found = _select_from_document(self.root, selector)
            return found[0] if found else None
        return self._wrapped.select_one(selector)


# ----------------------------------------------------------------------
# tree builder
# ----------------------------------------------------------------------


def _make_attr_dict(attrs: list[tuple[str, str | None]]) -> dict[str, object]:
    attr_dict: dict[str, object] = {}
    for raw_name, raw_value in attrs:
        attr_dict[raw_name.lower()] = raw_value  # last-wins; None if bare
    for name in _TOKENIZED_ATTRS & attr_dict.keys():
        value = attr_dict[name]
        if isinstance(value, str):
            attr_dict[name] = value.split()
        else:
            attr_dict[name] = []
    return attr_dict


class _TreeBuilder(HTMLParser):
    """Iterative builder: no recursion, tolerant of malformed input."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Document()
        self._stack: list[Element] = [self.root]

    def _current(self) -> Element:
        return self._stack[-1]

    def _pop_while_current_in(self, closers: frozenset[str]) -> None:
        while len(self._stack) > 1 and self._current().tag in closers:
            self._stack.pop()

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()

        implicit = _IMPLICIT_CLOSE.get(tag)
        if implicit:
            self._pop_while_current_in(implicit)
        if tag in _BLOCK_STARTERS and self._current().tag == "p":
            self._stack.pop()

        element = Element(tag, _make_attr_dict(attrs), parent=self._current())
        self._current().children.append(element)
        if tag not in VOID_ELEMENTS:
            self._stack.append(element)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()
        element = Element(tag, _make_attr_dict(attrs), parent=self._current())
        self._current().children.append(element)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]  # close through the match
                return
        # unmatched end tag: ignore (bs4/html.parser parity)

    def handle_data(self, data: str) -> None:
        if data:
            self._current().children.append(TextNode(data))

    # comments / doctype / processing instructions: dropped.


def parse_document(html: str) -> Document:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


# ----------------------------------------------------------------------
# CSS selector engine (subset)
# ----------------------------------------------------------------------
#
# Compiled form: tuple(compounds..., ) plus combinator list where
# compounds[i] describes what must match, combinators[i] says how
# compounds[i] relates to compounds[i+1]. Compound is the 4-tuple:
#     (tag_or_scope_or_None, ids, classes, ((name, op, value), ...))


def _compile_compound(text: str) -> tuple:
    tag: str | None = None
    ids: list[str] = []
    classes: list[str] = []
    attr_matchers: list[tuple[str, str | None, str]] = []

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "#" and i + 1 < n:
            end = _ident_end(text, i + 1)
            ids.append(text[i + 1 : end])
            i = end
        elif ch == "." and i + 1 < n:
            end = _ident_end(text, i + 1)
            classes.append(text[i + 1 : end])
            i = end
        elif ch == "[":
            end = text.find("]", i)
            if end == -1:
                raise SelectorError(f"unterminated '[' in {text!r}")
            attr_matchers.append(_compile_attr(text[i + 1 : end]))
            i = end + 1
        elif ch == ":":
            if text.startswith(_SCOPE, i):
                if tag is not None:
                    raise SelectorError(f"'{_SCOPE}' mid-compound {text!r}")
                tag = _SCOPE
                i += len(_SCOPE)
            else:
                raise SelectorError(
                    f"unsupported pseudo-class in {text!r}"
                )
        elif ch in {"+", "~"}:
            raise SelectorError(f"sibling combinators unsupported: {text!r}")
        else:
            end = _ident_end(text, i)
            name = text[i:end]
            if name != "*":
                if tag is not None and tag != _SCOPE and tag != name.lower():
                    raise SelectorError(
                        f"multiple type selectors in {text!r}"
                    )
                tag = _SCOPE if tag == _SCOPE else name.lower()
            i = end
        if i < n and text[i] == ":" and not text.startswith(_SCOPE, i):
            raise SelectorError(f"unsupported pseudo-class in {text!r}")

    if (
        tag is None
        and not ids
        and not classes
        and not attr_matchers
    ):
        raise SelectorError(f"empty compound in {text!r}")
    return (
        tag,
        tuple(ids),
        tuple(classes),
        tuple(attr_matchers),
    )


def _ident_end(text: str, start: int) -> int:
    i = start
    n = len(text)
    while i < n and (text[i].isalnum() or text[i] in "-_"):
        i += 1
    if i == start:
        raise SelectorError(f"missing identifier in {text!r}")
    return i


def _compile_attr(body: str) -> tuple[str, str | None, str]:
    body = body.strip()
    for op in ("*=", "="):
        idx = body.find(op)
        if idx == -1:
            continue
        name = body[:idx].strip().lower()
        if not name:
            raise SelectorError(f"missing attr name in [{body}]")
        value = body[idx + len(op) :].strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {'"', "'"}
        ):
            value = value[1:-1]
        return (name, op, value)
    if body.endswith("*"):
        raise SelectorError(f"bad attribute matcher [{body}]")
    name = body.lower()
    if not name or not all(c.isalnum() or c in "-_" for c in name):
        raise SelectorError(f"bad attribute name in [{body}]")
    return (name, None, "")


def _tokenize(selector: str) -> list[str]:
    """Split into compound strings and '>' markers."""
    tokens: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(selector)

    def flush() -> None:
        token = "".join(buf).strip()
        if token:
            tokens.append(token)
        del buf[:]

    while i < n:
        ch = selector[i]
        if ch == "[":
            end = selector.find("]", i)
            if end == -1:
                raise SelectorError(
                    f"unterminated '[' in selector {selector!r}"
                )
            buf.append(selector[i : end + 1])
            i = end + 1
        elif ch in {'"', "'"}:
            end = selector.find(ch, i + 1)
            if end == -1:
                raise SelectorError(f"unterminated quote in {selector!r}")
            buf.append(selector[i : end + 1])
            i = end + 1
        elif ch == ">":
            flush()
            tokens.append(">")
            i += 1
        elif ch.isspace():
            flush()
            i += 1
        else:
            buf.append(ch)
            i += 1
    flush()

    if tokens and tokens[0] == ">":
        raise SelectorError(f"selector may not start with '>': {selector!r}")
    return tokens


_CACHE: dict[str, tuple] = {}


def compile_selector(selector: str) -> tuple:
    cached = _CACHE.get(selector)
    if cached is not None:
        return cached

    raw = _tokenize(selector)
    compounds: list[tuple] = []
    combinators: list[str] = []
    expect_compound = True
    for token in raw:
        if token == ">":
            if expect_compound:
                raise SelectorError(
                    f"dangling '>' in selector {selector!r}"
                )
            combinators.append(">")
            expect_compound = True
        else:
            if not expect_compound:
                # Implicit descendant combinator between adjacent
                # compounds ("a b").
                combinators.append(" ")
            compounds.append(_compile_compound(token))
            expect_compound = False
    if not compounds or expect_compound:
        raise SelectorError(f"invalid selector: {selector!r}")

    compiled = (tuple(compounds), tuple(combinators))
    if len(_CACHE) < 512:
        _CACHE[selector] = compiled
    return compiled


_UNSET = object()


def _matches_compound(compound: tuple, el: Element, *, scope: Element) -> bool:
    tag, ids, classes, attr_matchers = compound

    if tag == _SCOPE:
        if el is not scope:
            return False
    elif tag is not None and el.tag != tag:
        return False

    if ids:
        el_id = el.get("id")
        if not isinstance(el_id, str) or any(cid != el_id for cid in ids):
            return False

    if classes:
        el_classes = el.get("class", [])
        if isinstance(el_classes, str):  # manual construction guard
            el_classes = el_classes.split()
        if any(cls not in el_classes for cls in classes):
            return False

    for name, op, expected in attr_matchers:
        actual = el.get(name, _UNSET)
        if actual is _UNSET:
            return False
        if op is None:
            continue
        if isinstance(actual, str):
            actual_str = actual
        elif isinstance(actual, list):
            actual_str = " ".join(str(v) for v in actual)
        else:  # bare attribute stored as None cannot satisfy '='/'*='
            return False
        if op == "=" and actual_str != expected:
            return False
        if op == "*=" and expected not in actual_str:
            return False
    return True


def _matches_chain(parsed: tuple, el: Element, *, scope: Element) -> bool:
    compounds, combinators = parsed
    if not _matches_compound(compounds[-1], el, scope=scope):
        return False
    return _match_leftward(compounds, len(compounds) - 2, combinators,
                            len(combinators) - 1, el, scope)


def _match_leftward(
    compounds: tuple,
    comp_idx: int,
    combinators: tuple,
    combo_idx: int,
    el: Element,
    scope: Element,
) -> bool:
    if comp_idx < 0:
        return True
    need = compounds[comp_idx]
    kind = combinators[combo_idx]

    if kind == ">":
        parent = el.parent
        if parent is None:
            return False
        if not _matches_compound(need, parent, scope=scope):
            return False
        return _match_leftward(compounds, comp_idx - 1, combinators,
                                combo_idx - 1, parent, scope)

    ancestor = el.parent
    while ancestor is not None:
        if _matches_compound(need, ancestor, scope=scope):
            if _match_leftward(compounds, comp_idx - 1, combinators,
                                combo_idx - 1, ancestor, scope):
                return True
        ancestor = ancestor.parent
    return False


__all__ = [
    "Element",
    "Document",
    "Minisoup",
    "TextNode",
    "SelectorError",
    "parse_document",
    "compile_selector",
    "VOID_ELEMENTS",
]
