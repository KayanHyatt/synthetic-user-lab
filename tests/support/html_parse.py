"""Structural reader for `sul.report.html`'s output, built on stdlib
`html.parser.HTMLParser` (PROJECT_SPEC.md §M5 plan: "Use stdlib html.parser
for the HTML -- do not add a parsing dependency, and do not regex HTML.").
Walks the actual element tree rather than matching substrings; entity
decoding (`&lt;`, `&amp;`, ...) is handled by `HTMLParser`'s own
`convert_charrefs=True` default, which is exactly what a round-trip-fidelity
test needs.

Used only by tests -- never imported by `sul.report`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class ParsedCluster:
    cluster_id: int
    title: str = ""
    finding_ids: list[int] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)


class _ReportHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.clusters: list[ParsedCluster] = []
        self.external_refs: list[str] = []
        self._current: ParsedCluster | None = None
        self._in_h2 = False
        self._h2_buffer: list[str] = []
        self._in_quote = False
        self._quote_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict: dict[str, str] = {k: v for k, v in attrs if v is not None}
        if tag == "section" and "cluster" in attr_dict.get("class", ""):
            cluster_id = int(attr_dict["data-cluster-id"])
            self._current = ParsedCluster(cluster_id=cluster_id)
            self.clusters.append(self._current)
        elif tag == "h2" and self._current is not None:
            self._in_h2 = True
            self._h2_buffer = []
        elif tag == "div" and "evidence" in attr_dict.get("class", ""):
            if self._current is not None and "data-finding-id" in attr_dict:
                self._current.finding_ids.append(int(attr_dict["data-finding-id"]))
        elif tag == "pre" and "quote" in attr_dict.get("class", ""):
            self._in_quote = True
            self._quote_buffer = []
        elif tag == "link" and attr_dict.get("href", "").startswith(
            ("http://", "https://")
        ):
            self.external_refs.append(attr_dict["href"])
        elif tag == "script" and attr_dict.get("src"):
            self.external_refs.append(attr_dict["src"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self._current is not None:
            self._current = None
        elif tag == "h2" and self._in_h2:
            self._in_h2 = False
            if self._current is not None:
                self._current.title = "".join(self._h2_buffer)
        elif tag == "pre" and self._in_quote:
            self._in_quote = False
            if self._current is not None:
                self._current.quotes.append("".join(self._quote_buffer))

    def handle_data(self, data: str) -> None:
        if self._in_h2:
            self._h2_buffer.append(data)
        if self._in_quote:
            self._quote_buffer.append(data)


def parse_report_html(text: str) -> tuple[list[ParsedCluster], list[str]]:
    """Returns (clusters, external_resource_refs)."""
    parser = _ReportHTMLParser()
    parser.feed(text)
    return parser.clusters, parser.external_refs


__all__ = ["ParsedCluster", "parse_report_html"]
