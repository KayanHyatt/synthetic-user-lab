"""Minimal structural reader for exactly the Markdown grammar
`sul.report.markdown` emits -- not a general CommonMark parser (none is a
project dependency; adding one wasn't asked for and the M5 plan scoped
"don't add a parsing dependency" to the HTML side specifically, where a
stdlib parser already exists). This mirrors the same idea for Markdown using
only the two structural markers our own template controls: `## Cluster N:`
headings and fenced code blocks (`` ``` `` .. `` ``` ``, backtick-run length
matched exactly via the same backreference CommonMark itself requires for a
closing fence).

Used only by tests -- never imported by `sul.report`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CLUSTER_HEADING = re.compile(r"^## Cluster (\d+): (.*)$", re.MULTILINE)
_FENCE = re.compile(r"^(`{3,})\n(.*?)\n^\1$", re.MULTILINE | re.DOTALL)


@dataclass
class ParsedCluster:
    cluster_id: int
    title: str
    quotes: list[str]


def parse_report_markdown(text: str) -> list[ParsedCluster]:
    """Split `text` at each `## Cluster N: title` heading and extract every
    fenced-code-block quote within that section.
    """
    headings = list(_CLUSTER_HEADING.finditer(text))
    clusters: list[ParsedCluster] = []
    for i, match in enumerate(headings):
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        section = text[start:end]
        quotes = [m.group(2) for m in _FENCE.finditer(section)]
        clusters.append(
            ParsedCluster(
                cluster_id=int(match.group(1)), title=match.group(2), quotes=quotes
            )
        )
    return clusters


__all__ = ["ParsedCluster", "parse_report_markdown"]
