"""HTML cleaner (P0-5, DESIGN §7): trafilatura primary, readability-lxml
fallback, custom fee-table preserver.

The 5-10x token reduction happens here, before any LLM sees the page. Fee
language is exactly where listings get vague (§9.5), and generic extractors
love to drop marketing-formatted fee tables — so tables whose text mentions
fees/deposits/pet charges are re-rendered row-by-row and appended under a
marker section when the extractor lost them.
"""

from __future__ import annotations

import hashlib
import re

import lxml.html
import trafilatura
from readability import Document

from manzil_worker.fetching.results import CleanedPage

FEE_TABLE_MARKER = "[FEE TABLES]"

_FEE_KEYWORDS = re.compile(
    r"\b(fee|fees|deposit|pet rent|pet fee|admin|application|parking|garage|trash|"
    r"utilit|water|sewer|surcharge|monthly charge|one[- ]time)\b",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def _normalize(text: str) -> str:
    text = _WHITESPACE.sub(" ", text)
    lines = [line.strip() for line in text.splitlines()]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def _extract_primary(html: str) -> str | None:
    return trafilatura.extract(
        html,
        include_tables=True,
        include_comments=False,
        favor_recall=True,
    )


def _extract_fallback(html: str) -> str:
    try:
        summary_html = Document(html).summary(html_partial=True)
        text = lxml.html.fromstring(summary_html).text_content()
    except Exception:
        try:
            text = lxml.html.fromstring(html).text_content()
        except Exception:
            return ""
    return text


def _fee_table_lines(html: str) -> list[str]:
    """Render each fee-bearing <table> as 'cell | cell | cell' lines."""
    try:
        tree = lxml.html.fromstring(html)
    except Exception:
        return []
    lines: list[str] = []
    for table in tree.iter("table"):
        table_text = table.text_content()
        if not _FEE_KEYWORDS.search(table_text):
            continue
        for row in table.iter("tr"):
            cells = [
                _WHITESPACE.sub(" ", cell.text_content()).strip() for cell in row.iter("td", "th")
            ]
            cells = [c for c in cells if c]
            if cells:
                lines.append(" | ".join(cells))
    return lines


def clean_html(html: str) -> CleanedPage:
    """Extract readable text, preserving fee tables the extractor dropped."""
    primary = _extract_primary(html)
    used_fallback = primary is None
    text = _normalize(primary if primary is not None else _extract_fallback(html))

    fee_lines = _fee_table_lines(html)
    # Only append rows the extractor actually lost — no duplication.
    missing = [line for line in fee_lines if line not in text]
    if missing:
        text = (
            f"{text}\n\n{FEE_TABLE_MARKER}\n" + "\n".join(missing)
            if text
            else (f"{FEE_TABLE_MARKER}\n" + "\n".join(missing))
        )

    return CleanedPage(
        text=text,
        text_hash=hashlib.sha256(text.encode()).hexdigest(),
        fee_tables_found=len(fee_lines),
        used_fallback=used_fallback,
    )
