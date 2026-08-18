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
Units in a separate sibling list. Generic extractors can keep enough Unit
prices to pass the price-retention guard while silently dropping every summary
card — severing each Unit from its category (beds/baths, plan name). Name- and
fact-bearing cards are therefore rendered compactly and appended when their
names are missing from the primary/fallback text; when a card carries a
distinct unit grid, its units are nested (indented) beneath the header so the
category stays attached to them. Two guardrails keep this from mis-associating
units across a multi-card container (see _floor_plan_lines).

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
from manzil_shared.config import CLEANED_PAGE_MAX_CHARS
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
_UNIT_ROW_ID = re.compile(
    r"\b(?:unit|apt|apartment|suite)\b[\s#:.-]*[\w-]*\d|#\s?\d", re.IGNORECASE
)
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


def _unit_rows(card: lxml.html.HtmlElement, header: lxml.html.HtmlElement) -> list[str]:
    """Compact text of unit rows inside ``card`` but outside its ``header``.

    A unit row carries a price (or rent-status) *and* a unit identifier such as
    ``Unit 03-205``. Requiring the identifier is what keeps grid header rows
    ("Unit Base Price Sq Ft") and availability blurbs ("1 Available unit") out.
    Structured ``<li>``/``<tr>`` rows are preferred; otherwise the smallest
    identifier-bearing elements (those with no matching descendant) are used.
    """
    header_nodes = set(header.iter())
    rows: list[str] = []
    seen: set[str] = set()

    def _is_unit(text: str) -> bool:
        return bool(
            text
            and _UNIT_ROW_ID.search(text)
            and (_PRICE_TOKEN.search(text) or _RENT_STATUS.search(text))
        )

    for element in card.xpath(".//li | .//tr"):
        if element in header_nodes:
            continue
        row = _normalize(_text_without_actions(element))
        if _is_unit(row) and row not in seen:
            seen.add(row)
            rows.append(row)
    if rows:
        return rows

    for element in card.iter():
        if element in header_nodes or element is header:
            continue
        row = _normalize(_text_without_actions(element))
        if not _is_unit(row) or row in seen:
            continue
        # Skip containers: keep only the minimal element with no matching child.
        if any(_is_unit(_normalize(_text_without_actions(child))) for child in element):
            continue
        seen.add(row)
        rows.append(row)
    return rows


def _floor_plan_lines(html: str) -> list[tuple[str, str]]:
    """Return ``(name, block)`` for compact, semantic Floor Plan cards.

    ``block`` is the header summary (name, rent range, beds/baths, sqft); when
    the card carries a distinct unit grid, each available unit is indented
    beneath it, so the extractor-dropped category stays attached to its units.

    The signal is structural, not domain-specific: a class/id such as
    ``floorplan-name``, ``modelName`` or ``fp-name`` inside a card that also
    carries a price and a Floor Plan fact. Unit nesting is bounded by two
    guardrails against mis-association (see inline comments).
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

        # 1. Header region: the smallest ancestor whose text has a price/rent
        #    status and a Floor Plan fact.
        header = None
        header_summary = ""
        context = element
        for _ in range(7):
            summary = _text_without_actions(context)
            has_rent = _PRICE_TOKEN.search(summary) or _RENT_STATUS.search(summary)
            if has_rent and _FLOOR_PLAN_FACT.search(summary):
                header = context
                header_summary = _normalize(summary)
                break
            parent = context.getparent()
            if parent is None:
                break
            context = parent
        if header is None:
            continue

        key = (name, header_summary)
        if key in seen:
            continue
        seen.add(key)

        # 2. Climb to the smallest ancestor that adds unit rows. Guardrails:
        #    (a) stop as soon as unit rows appear — never keep climbing;
        #    (b) abort nesting (header-only) if an ancestor spans more than one
        #        plan name, i.e. a multi-card container, where units cannot be
        #        safely attributed to a single plan.
        unit_rows: list[str] = []
        card = header.getparent()
        for _ in range(5):
            if card is None:
                break
            name_hits = sum(
                1
                for node in card.iter()
                if _PLAN_NAME_HINT.search(" ".join((node.get("class", ""), node.get("id", ""))))
            )
            if name_hits > 1:
                break
            rows = _unit_rows(card, header)
            if rows:
                unit_rows = rows
                break
            card = card.getparent()

        if unit_rows:
            block = header_summary + "\n" + "\n".join(f"  {row}" for row in unit_rows)
        else:
            block = header_summary
        lines.append((name, block))
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
    prose_text = _normalize(text)

    fee_lines = _fee_table_lines(html)
    # Only append rows the extractor actually lost — no duplication.
    missing = [line for line in fee_lines if line not in prose_text]
    fee_section = ""
    if missing:
        fee_section = f"{FEE_TABLE_MARKER}\n" + "\n".join(missing)

    floor_plan_lines = _floor_plan_lines(html)
    missing_plans = [block for name, block in floor_plan_lines if name not in prose_text]
    floor_plan_section = ""
    if missing_plans:
        floor_plan_section = f"{FLOOR_PLAN_MARKER}\n" + "\n".join(missing_plans)

    digest, embedded_blobs = extract_embedded_data(html)
    embedded_section = f"{EMBEDDED_DATA_MARKER}\n{digest}" if digest else ""

    def bounded(section: str, limit: int) -> str:
        if len(section) <= limit:
            return section
        suffix = "\n…[cleaned text truncated]"
        return section[: max(0, limit - len(suffix))] + suffix if limit else ""

    # Generic prose is the least reliable/valuable component once the cleaner
    # has recovered explicit fee and Floor Plan blocks. Preserve embedded JSON,
    # then Floor Plans and fees, before allocating the remaining page budget to
    # prose. The final combined text is always bounded.
    embedded_section = bounded(embedded_section, CLEANED_PAGE_MAX_CHARS)
    remaining = CLEANED_PAGE_MAX_CHARS - len(embedded_section)
    floor_plan_section = bounded(floor_plan_section, remaining)
    remaining -= len(floor_plan_section)
    fee_section = bounded(fee_section, remaining)
    remaining -= len(fee_section)
    prose_text = bounded(prose_text, remaining)
    content_sections = [
        section for section in (prose_text, fee_section, floor_plan_section) if section
    ]
    content_text = "\n\n".join(content_sections)
    text = "\n\n".join(section for section in (content_text, embedded_section) if section)

    return CleanedPage(
        text=text,
        text_hash=hashlib.sha256(text.encode()).hexdigest(),
        content_text=content_text,
        embedded_data=digest,
        fee_tables_found=len(fee_lines),
        used_fallback=used_fallback,
        embedded_blobs=embedded_blobs,
    )
