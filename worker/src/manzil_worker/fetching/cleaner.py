"""HTML cleaner (P0-5, DESIGN §7): trafilatura primary, readability-lxml
fallback, custom fee-table preserver, embedded structured-data digest.

The 5-10x token reduction happens here, before any LLM sees the page. Fee
language is exactly where listings get vague (§9.5), and generic extractors
love to drop marketing-formatted fee tables — so tables whose text mentions
fees/deposits/pet charges are re-rendered row-by-row and appended under a
marker section when the extractor lost them. Listing sites also ship their
data as JSON in script tags (JSON-LD, __NEXT_DATA__, preloaded state) that no
text extractor sees — the miner (structured.py, §20 v2.6) appends a pruned
digest of it under [EMBEDDED DATA].

Price-retention guard: generic extractors can silently discard the listing
data itself — rentcafe wraps the page in class "main-content-before-contact",
which trafilatura's body-detection xpaths match ("main-content"), flipping it
into strict paragraph extraction that prunes floor-plan cards built from
<b>/<span> inside plain <div>s (readability fares no better: "contact" hits
its negative-class regex). An extraction that kept fewer than half of the
distinct price tokens visibly rendered on the page is therefore rejected, and
the cleaner degrades: trafilatura → readability → script-stripped visible
text. Fewer tokens saved on such pages, but the facts survive.
"""

from __future__ import annotations

import hashlib
import re

import lxml.html
import trafilatura
from readability import Document

from manzil_worker.fetching.results import CleanedPage
from manzil_worker.fetching.structured import EMBEDDED_DATA_MARKER, extract_embedded_data

FEE_TABLE_MARKER = "[FEE TABLES]"

_FEE_KEYWORDS = re.compile(
    r"\b(fee|fees|deposit|pet rent|pet fee|admin|application|parking|garage|trash|"
    r"utilit|water|sewer|surcharge|monthly charge|one[- ]time)\b",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_PRICE_TOKEN = re.compile(r"\$\s?\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\$\s?\d{2,}(?:\.\d{2})?")
_NON_TEXT_TAGS = ("script", "style", "noscript", "template", "svg", "iframe")


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
        return lxml.html.fromstring(summary_html).text_content()
    except Exception:
        return ""


def _visible_text(html: str) -> str:
    """Rendered text of the whole page: everything except non-text subtrees."""
    try:
        tree = lxml.html.fromstring(html)
    except Exception:
        return ""
    for element in [el for tag in _NON_TEXT_TAGS for el in tree.iter(tag)]:
        element.drop_tree()
    return tree.text_content()


def _price_tokens(text: str) -> set[str]:
    return {token.replace(" ", "") for token in _PRICE_TOKEN.findall(text)}


def _keeps_prices(text: str, rendered_prices: set[str]) -> bool:
    """Did an extraction retain at least half of the page's rendered prices?"""
    if not rendered_prices:
        return True
    return len(_price_tokens(text) & rendered_prices) * 2 >= len(rendered_prices)


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
    visible = _visible_text(html)
    rendered_prices = _price_tokens(visible)

    primary = _extract_primary(html)
    used_fallback = primary is None or not _keeps_prices(primary, rendered_prices)
    if not used_fallback:
        text = primary
    else:
        text = _extract_fallback(html)
        if not text.strip() or not _keeps_prices(text, rendered_prices):
            text = visible
    text = _normalize(text)

    fee_lines = _fee_table_lines(html)
    # Only append rows the extractor actually lost — no duplication.
    missing = [line for line in fee_lines if line not in text]
    if missing:
        text = (
            f"{text}\n\n{FEE_TABLE_MARKER}\n" + "\n".join(missing)
            if text
            else (f"{FEE_TABLE_MARKER}\n" + "\n".join(missing))
        )

    digest, embedded_blobs = extract_embedded_data(html)
    if digest:
        section = f"{EMBEDDED_DATA_MARKER}\n{digest}"
        text = f"{text}\n\n{section}" if text else section

    return CleanedPage(
        text=text,
        text_hash=hashlib.sha256(text.encode()).hexdigest(),
        fee_tables_found=len(fee_lines),
        used_fallback=used_fallback,
        embedded_blobs=embedded_blobs,
    )
