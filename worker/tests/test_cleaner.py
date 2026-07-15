"""P0-5: cleaner behavior — extraction, fee-table preservation, fallback, hashing."""

from __future__ import annotations

import manzil_worker.fetching.cleaner as cleaner_module
from manzil_worker.fetching.cleaner import FEE_TABLE_MARKER, clean_html

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
