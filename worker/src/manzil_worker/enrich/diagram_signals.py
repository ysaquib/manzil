"""Deterministic Floor Plan diagram detection (P3-SC5 item 3).

DESIGN asks that explicit diagrams be classified "deterministically where
possible", leaving the vision classifier as the fallback for the rest. This
module is that deterministic pass: pure, no LLM, no I/O, no visual inference.

The bar is deliberately *evidence*, not resemblance. A candidate qualifies only
when the page said so — it sits inside a floor-plan card, carries a Source
native plan ID, or its own alt/title/caption names a floor plan. Filename
resemblance alone is explicitly insufficient (workbook §7.2), because
`plan-b.jpg` is as likely to be a marketing shot as a layout.

A false positive here is more expensive than a miss: it spends the diagram
budget, stores a photo at the larger profile, and can attach a photo to a plan.
A miss merely falls through to IMAGE_CLASSIFY.
"""

from __future__ import annotations

import re

# Phrases that name the artifact, not the room. "plan" alone is far too loose —
# "meal plan", "site plan", and "plan your visit" all appear on listing pages.
_DIAGRAM_PHRASES = (
    "floor plan",
    "floorplan",
    "floor-plan",
    "unit plan",
    "site map",
    "layout diagram",
)

# Bare "layout" and "diagram" count only when the text is short and clearly
# labelling the asset, so a paragraph mentioning "an open layout" doesn't win.
_WEAK_PHRASES = ("layout", "diagram", "schematic")
_WEAK_MAX_WORDS = 5

_WHITESPACE = re.compile(r"\s+")


def _normalize(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return _WHITESPACE.sub(" ", value).strip().casefold()


def _text_names_a_plan(value: object) -> bool:
    text = _normalize(value)
    if not text:
        return False
    if any(phrase in text for phrase in _DIAGRAM_PHRASES):
        return True
    return len(text.split()) <= _WEAK_MAX_WORDS and any(phrase in text for phrase in _WEAK_PHRASES)


def looks_like_diagram(context: object) -> bool:
    """True when the page itself identifies this candidate as a Floor Plan diagram.

    `context` is an `ImageCandidateIn`/`DiscoveredImage` or the equivalent
    mapping, so IMAGE_FETCH can call it before or after model conversion.
    """

    def field(name: str) -> object:
        if hasattr(context, name):
            return getattr(context, name)
        if isinstance(context, dict):
            return context.get(name)
        return None

    # Structural evidence: the page grouped this image with one Floor Plan.
    if field("source_native_plan_id"):
        return True
    if bool(field("containing_floor_plan_card")):
        return True
    # Self-description: the image's own accessible text names the artifact.
    return any(_text_names_a_plan(field(name)) for name in ("alt", "title", "caption"))
