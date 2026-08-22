"""Structural reader for `sul.web` dashboard pages, mirroring
`tests/support/html_parse.py`'s approach (stdlib `html.parser`, no parsing
dependency, no regex over HTML) but general-purpose: every element's tag,
attributes, id and ancestor-id chain, plus verbatim `<pre class="quote">`
text and every external resource reference.

The ancestor-id chain is what makes "can an HTMX swap replace or hide the
standing caveat" (PROJECT_SPEC.md §M7 5.3) a structural check rather than a
substring/ordering guess: for the caveat's own parsed element, the test
checks whether any `hx-target` (or self-targeting `hx-get`) element's id
appears in that chain -- i.e. whether the caveat is nested *inside* a swap
target, not merely whether it renders somewhere on the page.

Used only by tests -- never imported by `sul.web`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


@dataclass
class ParsedElement:
    tag: str
    attrs: dict[str, str]
    id: str | None
    ancestor_ids: list[str] = field(default_factory=list)


@dataclass
class ParsedPage:
    elements: list[ParsedElement] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    external_refs: list[str] = field(default_factory=list)
    text: str = ""


class _DashboardHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[ParsedElement] = []
        self.quotes: list[str] = []
        self.external_refs: list[str] = []
        self.text_chunks: list[str] = []
        self._in_quote = False
        self._quote_buffer: list[str] = []
        self._stack: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict: dict[str, str] = {k: v for k, v in attrs if v is not None}
        el_id = attr_dict.get("id")
        ancestor_ids = [aid for _, aid in self._stack if aid]
        self.elements.append(
            ParsedElement(tag=tag, attrs=attr_dict, id=el_id, ancestor_ids=ancestor_ids)
        )
        if tag == "pre" and "quote" in attr_dict.get("class", ""):
            self._in_quote = True
            self._quote_buffer = []
        if tag == "link" and attr_dict.get("href", "").startswith(
            ("http://", "https://")
        ):
            self.external_refs.append(attr_dict["href"])
        if tag == "script":
            src = attr_dict.get("src", "")
            if src.startswith(("http://", "https://")):
                self.external_refs.append(src)
        if tag not in _VOID_TAGS:
            self._stack.append((tag, el_id))

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre" and self._in_quote:
            self._in_quote = False
            self.quotes.append("".join(self._quote_buffer))
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break

    def handle_data(self, data: str) -> None:
        self.text_chunks.append(data)
        if self._in_quote:
            self._quote_buffer.append(data)


def parse_dashboard_page(text: str) -> ParsedPage:
    parser = _DashboardHTMLParser()
    parser.feed(text)
    return ParsedPage(
        elements=parser.elements,
        quotes=parser.quotes,
        external_refs=parser.external_refs,
        text="".join(parser.text_chunks),
    )


def htmx_swap_target_ids(page: ParsedPage) -> set[str]:
    """Every element id an HTMX swap on this page could write into: an
    explicit `hx-target="#id"`, or (HTMX's own default) the element's own id
    when it carries `hx-get`/`hx-post` with no `hx-target`.
    """
    target_ids: set[str] = set()
    for el in page.elements:
        hx_target = el.attrs.get("hx-target")
        if hx_target and hx_target.startswith("#"):
            target_ids.add(hx_target[1:])
        elif ("hx-get" in el.attrs or "hx-post" in el.attrs) and el.id:
            target_ids.add(el.id)
    return target_ids


__all__ = [
    "ParsedElement",
    "ParsedPage",
    "htmx_swap_target_ids",
    "parse_dashboard_page",
]
