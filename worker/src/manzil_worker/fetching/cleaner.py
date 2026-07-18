"""HTML cleaner (P0-5, DESIGN §7): trafilatura primary, readability-lxml
fallback, custom fact preservers, embedded structured-data digest.

The 5-10x token reduction happens here, before any LLM sees the page. Fee
language is exactly where listings get vague (§9.5), and generic extractors
love to drop marketing-formatted fee tables — so tables whose text mentions
fees/deposits/pet charges are re-rendered row-by-row and appended under a
marker section when the extractor lost them. Listing sites also ship their
data as JSON in script tags (JSON-LD, __NEXT_DATA__, preloaded state) that no
text extractor sees — the miner (structured.py, §20 v2.6) appends a pruned
digest of it under [EMBEDDED DATA].

Floor-plan-card retention guard: some listing pages put the Floor Plan summary
(name, rent range, beds/baths, sqft) in a span-only card and the available
Units in a separate list. Generic extractors can keep enough Unit prices to
pass the price-retention guard while silently dropping every summary card.
Name-bearing, fact-bearing cards are therefore rendered compactly and appended
when their names are missing from the primary/fallback text.

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
FLOOR_PLAN_MARKER = "[FLOOR PLANS]"

_FEE_KEYWORDS = re.compile(
    r"\b(fee|fees|deposit|pet rent|pet fee|admin|application|parking|garage|trash|"
    r"utilit|water|sewer|surcharge|monthly charge|one[- ]time)\b",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_PRICE_TOKEN = re.compile(r"\$\s?\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\$\s?\d{2,}(?:\.\d{2})?")
_NON_TEXT_TAGS = ("script", "style", "noscript", "template", "svg", "iframe")
_PLAN_NAME_HINT = re.compile(
    r"(?:floor[\W_]*plan|model|fp)[\W_]*name|name[\W_]*(?:floor[\W_]*plan|model)",
    re.IGNORECASE,
)
_FLOOR_PLAN_FACT = re.compile(
    r"\b(?:studio|\d+(?:\.\d+)?\s*(?:beds?|baths?)|[\d,]+\s*sq(?:uare)?\s*ft)\b",
    re.IGNORECASE,
)
_RENT_STATUS = re.compile(r"\b(?:call|contact(?: us)?) for (?:rent|pricing)\b", re.IGNORECASE)
_CARD_TEXT_XPATH = (
    ".//text()[not(ancestor::a) and not(ancestor::button) and not(ancestor::script) "
    "and not(ancestor::style) and not(ancestor::noscript) and not(ancestor::template) "
    "and not(ancestor::svg) and not(ancestor::iframe)]"
)


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


def _text_without_actions(element: lxml.html.HtmlElement) -> str:
    """Compact visible card text without CTA/link copy."""
    parts = []
    for text_node in element.xpath(_CARD_TEXT_XPATH):
        value = _WHITESPACE.sub(" ", str(text_node)).strip()
        if value:
            parts.append(value)
    return " ".join(parts)


def _floor_plan_lines(html: str) -> list[tuple[str, str]]:
    """Return ``(name, summary)`` for compact, semantic Floor Plan cards.

    The signal is deliberately structural rather than domain-specific: a
    class/id such as ``floorplan-name``, ``modelName`` or ``fp-name`` must be
    inside a nearby card containing both a price and a Floor Plan fact. This
    excludes generic model labels and navigation headings.
    """
    try:
        tree = lxml.html.fromstring(html)
    except Exception:
        return []

    lines: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for element in tree.xpath("//*[@class or @id]"):
        hint = " ".join((element.get("class", ""), element.get("id", "")))
        if not _PLAN_NAME_HINT.search(hint):
            continue
        name = _normalize(_text_without_actions(element))
        if not name or "\n" in name or len(name) > 160:
            continue

        context = element
        for _ in range(7):
            summary = _text_without_actions(context)
            has_rent = _PRICE_TOKEN.search(summary) or _RENT_STATUS.search(summary)
            if has_rent and _FLOOR_PLAN_FACT.search(summary):
                item = (name, summary)
                if item not in seen:
                    seen.add(item)
                    lines.append(item)
                break
            parent = context.getparent()
            if parent is None:
                break
            context = parent
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

    floor_plan_lines = _floor_plan_lines(html)
    missing_plans = [summary for name, summary in floor_plan_lines if name not in text]
    if missing_plans:
        section = f"{FLOOR_PLAN_MARKER}\n" + "\n".join(missing_plans)
        text = f"{text}\n\n{section}" if text else section

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
