"""P0-5: cleaner behavior — extraction, fee-table preservation, fallback, hashing."""

from __future__ import annotations

from pathlib import Path

import lxml.html
import manzil_worker.fetching.cleaner as cleaner_module
import pytest
from manzil_worker.fetching.cleaner import (
    FEE_TABLE_MARKER,
    FLOOR_PLAN_MARKER,
    _unit_rows,
    clean_html,
)


def test_unit_rows_extracts_identifier_rows_and_skips_headers() -> None:
    html = """
    <div id="card">
      <div class="modelName-wrap"><span class="modelName">The Elm</span>
        <span>1 Bed 1 Bath 700 Sq Ft $1,400</span></div>
      <div class="grid">
        <div class="unitGridHeaderRow">Unit Base Price Sq Ft Availability</div>
        <ul>
          <li>Unit 12-104 price $1,400 square feet 700 availibility Now</li>
          <li>Unit 12-106 price $1,450 square feet 700 availibility Sep 2</li>
        </ul>
        <div>2 Available units</div>
      </div>
    </div>
    """
    tree = lxml.html.fromstring(html)
    card = tree.xpath("//*[@id='card']")[0]
    header = tree.xpath("//*[contains(@class,'modelName-wrap')]")[0]

    rows = _unit_rows(card, header)

    assert rows == [
        "Unit 12-104 price $1,400 square feet 700 availibility Now",
        "Unit 12-106 price $1,450 square feet 700 availibility Sep 2",
    ]
    # The grid header row ("Unit Base Price…") has no unit identifier -> excluded.
    # "2 Available units" has no price and no identifier -> excluded.
    assert not any("Base Price" in r for r in rows)
    assert not any("Available units" in r for r in rows)


LISTING_HTML = """
<html><head><title>Maple Court Apartments</title></head><body>
<nav>Home | Floor Plans | Contact</nav>
<main>
  <h1>Maple Court Apartments</h1>
  <p>{filler}</p>
  <table>
    <tr><th>Fee</th><th>Amount</th></tr>
    <tr><td>Application fee</td><td>$75</td></tr>
    <tr><td>Admin fee</td><td>$150</td></tr>
    <tr><td>Pet rent</td><td>$35/mo</td></tr>
  </table>
  <table>
    <tr><td>Mon-Fri</td><td>9am-6pm</td></tr>
  </table>
</main>
</body></html>
""".format(filler="Spacious two bedroom apartments in Detroit, Michigan. " * 40)


def test_fee_table_rows_survive_cleaning() -> None:
    cleaned = clean_html(LISTING_HTML)
    for fragment in ("Application fee", "$75", "Admin fee", "$150", "Pet rent", "$35/mo"):
        assert fragment in cleaned.text
    assert cleaned.fee_tables_found == 4  # header + 3 fee rows; hours table ignored


def test_fee_rows_not_duplicated_when_extractor_kept_them() -> None:
    cleaned = clean_html(LISTING_HTML)
    assert cleaned.text.count("Application fee | $75") == 1


def test_non_fee_tables_are_not_preserved() -> None:
    cleaned = clean_html(LISTING_HTML)
    if FEE_TABLE_MARKER in cleaned.text:
        preserved = cleaned.text.split(FEE_TABLE_MARKER, 1)[1]
        assert "Mon-Fri" not in preserved


def test_fallback_used_when_trafilatura_extracts_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cleaner_module, "_extract_primary", lambda html: None)
    cleaned = clean_html(LISTING_HTML)
    assert cleaned.used_fallback is True
    assert "Maple Court" in cleaned.text


# Reproduces the rentcafe.com failure: a wrapper class matching trafilatura's
# main-content heuristics ("main-content") flips it into strict paragraph
# extraction, which prunes listing cards whose facts live in <b>/<span> inside
# plain <div>s. The cleaner must detect the price loss and fall back.
_CARDS = "\n".join(
    f"""<div class="fp-item">
      <div class="fp-info">
        <b class="fp-name">The Plan {i}</b>
        <span>1 Bed</span><span> / 1 Bath</span><span> / 850 Sqft</span>
        <span class="fp-price">$1,{600 + i} - $2,075</span>
        <a href="#">Floor plan details</a>
      </div>
      <p>Check for available units</p>
    </div>"""
    for i in range(8)
)
CARD_LISTING_HTML = f"""<html><head><title>Uptown</title></head><body>
<nav>Home | Floor Plans | Contact</nav>
<div class="main-content-wrapper">
  <h1>Uptown Apartments</h1>
  <p>{"Spacious one and two bedroom apartments in Detroit, Michigan. " * 30}</p>
  <div class="floorplans">{_CARDS}</div>
  <p>Contact the property for more information.</p>
</div>
</body></html>"""


def test_listing_cards_survive_main_content_wrapper() -> None:
    cleaned = clean_html(CARD_LISTING_HTML)
    for fragment in ("The Plan 0", "The Plan 7", "$1,600", "$1,607", "850 Sqft"):
        assert fragment in cleaned.text
    assert cleaned.used_fallback is True


def test_price_guard_does_not_fire_when_extraction_keeps_prices() -> None:
    cleaned = clean_html(LISTING_HTML)
    assert cleaned.used_fallback is False


FLOOR_PLAN_CARD_HTML = """
<html><body><main>
  <h1>Village Apartments</h1>
  <p>{filler}</p>
  <div class="pricingGridItem">
    <div class="priceBedRangeInfo">
      <span class="modelName">The Birch</span>
      <span class="rentLabel">$1,290 - $1,320</span>
      <span class="detailsLabel">Studio · 1 Bath · 625 Sq Ft</span>
      <button>View The Birch Floor Plan Details</button>
    </div>
    <span>Unit 03-205 price $1,320 square feet 625</span>
  </div>
  <div class="pricingGridItem">
    <div class="priceBedRangeInfo">
      <span class="floorplan-name">The Cedar</span>
      <span class="rentLabel">$1,395 - $1,485</span>
      <span class="detailsLabel">1 Bed · 1 Bath · 775 Sq Ft</span>
      <a href="#cedar">Floor Plan Details</a>
    </div>
    <span>Unit 04-102 price $1,480 square feet 775</span>
  </div>
  <div class="pricingGridItem">
    <div class="priceBedRangeInfo">
      <span class="modelName">The Dogwood</span>
      <span class="rentLabel">Call for Rent</span>
      <span class="detailsLabel">2 Beds · 2 Baths · 1,050 Sq Ft</span>
      <button>View The Dogwood Floor Plan Details</button>
      <span>Not Available</span>
    </div>
  </div>
</main></body></html>
""".format(filler="Apartments in Detroit, Michigan. " * 40)


def test_floor_plan_cards_survive_when_unit_prices_mask_primary_loss(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Three retained prices are over half of the five rendered prices, so the
    # existing price guard alone accepts this deliberately lossy extraction.
    monkeypatch.setattr(
        cleaner_module,
        "_extract_primary",
        lambda html: (
            "Apartments in Detroit. Unit price $1,320. Unit price $1,480. Advertised minimum $1,395."
        ),
    )

    cleaned = clean_html(FLOOR_PLAN_CARD_HTML)

    assert cleaned.used_fallback is False
    assert FLOOR_PLAN_MARKER in cleaned.text
    assert "The Birch $1,290 - $1,320 Studio · 1 Bath · 625 Sq Ft" in cleaned.text
    assert "The Cedar $1,395 - $1,485 1 Bed · 1 Bath · 775 Sq Ft" in cleaned.text
    assert "The Dogwood Call for Rent 2 Beds · 2 Baths · 1,050 Sq Ft Not Available" in cleaned.text
    preserved = cleaned.text.split(FLOOR_PLAN_MARKER, 1)[1]
    assert "Floor Plan Details" not in preserved
    # Units now nest (two-space indent) under their plan header.
    assert "  Unit 03-205 price $1,320 square feet 625" in cleaned.text
    assert "  Unit 04-102 price $1,480 square feet 775" in cleaned.text
    # The Dogwood has no distinct unit -> header-only, no nested unit line.
    dogwood_tail = cleaned.text.split("The Dogwood", 1)[1]
    assert not dogwood_tail.lstrip().startswith("Unit")


FLOOR_PLAN_GROUP_HTML = """
<html><body><main>
  <h1>Grouped Apartments</h1>
  <p>{filler}</p>
  <div class="fp-group">
    <div class="model-row">
      <span class="modelName">Plan Alpha</span>
      <span>1 Bed 1 Bath 800 Sq Ft $1,500</span>
    </div>
    <div class="model-row">
      <span class="modelName">Plan Beta</span>
      <span>2 Beds 2 Baths 1,100 Sq Ft $1,900</span>
    </div>
    <ul>
      <li>Unit A1 price $1,500 square feet 800 availibility Now</li>
      <li>Unit B1 price $1,900 square feet 1,100 availibility Now</li>
    </ul>
  </div>
</main></body></html>
""".format(filler="Apartments in Detroit, Michigan. " * 40)


def test_multi_card_container_falls_back_to_header_only(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Force the floor-plan guard to run by making primary extraction lossy but
    # price-retaining.
    monkeypatch.setattr(
        cleaner_module,
        "_extract_primary",
        lambda html: "Grouped apartments in Detroit. $1,500. $1,900.",
    )

    cleaned = clean_html(FLOOR_PLAN_GROUP_HTML)

    assert FLOOR_PLAN_MARKER in cleaned.text
    assert "Plan Alpha 1 Bed 1 Bath 800 Sq Ft $1,500" in cleaned.text
    assert "Plan Beta 2 Beds 2 Baths 1,100 Sq Ft $1,900" in cleaned.text
    # A shared container spans two plan names, so units must NOT be nested
    # (nesting would mis-attribute Unit B1 to Plan Alpha).
    assert "  Unit A1" not in cleaned.text
    assert "  Unit B1" not in cleaned.text


def test_floor_plan_cards_are_not_duplicated_when_extractor_kept_them(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        cleaner_module,
        "_extract_primary",
        lambda html: "The Birch $1,290. Unit $1,480. Advertised minimum $1,395.",
    )

    cleaned = clean_html(FLOOR_PLAN_CARD_HTML)

    assert cleaned.text.count("The Birch $1,290") == 1
    assert "The Cedar $1,395 - $1,485" in cleaned.text


def test_visible_text_fallback_excludes_script_bodies() -> None:
    html = CARD_LISTING_HTML.replace(
        "</body>", "<script>var state = {secret: 'not page text'};</script></body>"
    )
    cleaned = clean_html(html)
    assert "not page text" not in cleaned.text.split("[EMBEDDED DATA]")[0]


def test_hash_is_deterministic_and_content_sensitive() -> None:
    a = clean_html(LISTING_HTML)
    b = clean_html(LISTING_HTML)
    c = clean_html(LISTING_HTML.replace("$75", "$95"))
    assert a.text_hash == b.text_hash
    assert a.text_hash != c.text_hash


def test_empty_and_garbage_input_do_not_raise() -> None:
    assert clean_html("").text == ""
    assert clean_html("<<<not html>>>").text_hash


_FIXTURES = Path(__file__).parent / "fixtures"


def _floor_plan_blocks(section: str) -> dict[str, list[str]]:
    """Parse a [FLOOR PLANS] section into {header_line: [unit_line, ...]}."""
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in section.splitlines():
        if not line.strip():
            continue
        if line.startswith("  ") and current is not None:
            blocks[current].append(line.strip())
        elif not line.startswith("  "):
            current = line
            blocks[current] = []
    return blocks


def test_apartments_com_units_nest_under_their_category() -> None:
    raw_path = _FIXTURES / "corpus/apartments.com--village-of-detroit/raw.html"
    if not raw_path.exists():
        pytest.skip("local corpus fixture not present (gitignored)")
    cleaned = clean_html(raw_path.read_text(encoding="utf-8", errors="ignore"))
    assert FLOOR_PLAN_MARKER in cleaned.text

    section = cleaned.text.split(FLOOR_PLAN_MARKER, 1)[1]
    blocks = _floor_plan_blocks(section)

    studio_hdr = next(h for h in blocks if "Studio 1 Bath" in h)
    assert any("Unit 03-205" in u for u in blocks[studio_hdr])

    two_bed_hdr = next(h for h in blocks if "2 Beds 2 Baths" in h)
    assert any("Unit 09-205" in u for u in blocks[two_bed_hdr])


def test_clean_html_survives_entire_corpus() -> None:
    raws = sorted((_FIXTURES / "corpus").glob("*/raw.html"))
    if not raws:
        pytest.skip("local corpus not present (gitignored)")
    for raw in raws:
        cleaned = clean_html(raw.read_text(encoding="utf-8", errors="ignore"))
        assert cleaned.text_hash, f"empty clean for {raw.parent.name}"
