"""Embedded structured-data miner (§20 v2.6): JSON-LD + state blobs into the
cleaned text, noise and wrong-property subtrees pruned, shells reclassified."""

from __future__ import annotations

import json

from manzil_shared.config import EMBEDDED_DATA_MAX_CHARS
from manzil_shared.models import FetchOutcome
from manzil_worker.fetching.classifier import classify
from manzil_worker.fetching.cleaner import clean_html
from manzil_worker.fetching.results import FetchResult
from manzil_worker.fetching.structured import EMBEDDED_DATA_MARKER, extract_embedded_data


def page(*scripts: str, body_text: str = "") -> str:
    return f"<html><head>{''.join(scripts)}</head><body><p>{body_text}</p></body></html>"


def ld(payload: dict | list) -> str:
    return f'<script type="application/ld+json">{json.dumps(payload)}</script>'


LISTING_LD = {
    "@context": "https://schema.org",
    "@type": "ApartmentComplex",
    "name": "Maple Court",
    "address": {"@type": "PostalAddress", "streetAddress": "1 Maple St"},
    "numberOfBedrooms": 2,
}

FLOORPLAN_STATE = {
    "listing": {
        "name": "Maple Court",
        "floorPlans": [
            {"name": "A1", "bedCount": 1, "priceRange": {"min": 1443, "max": 1443}, "sqFt": 733},
            {"name": "B2", "bedCount": 2, "priceRange": {"min": 1650, "max": 1720}, "sqFt": 980},
        ],
    },
    "abTestingData": {"featureMap": {"prioritize_floor_plans": True}},
    "similar": [{"floorPlans": [{"name": "OTHER", "priceRange": {"min": 999}}]}],
}


def state_script(payload: dict, assign: str = "window.__PRELOADED_STATE__") -> str:
    """Realistic multi-statement state script, long enough to clear the
    EMBEDDED_SCRIPT_MIN_CHARS candidate floor."""
    blob = json.dumps(payload)
    padding = "".join(f"var pad{i} = 1;\n" for i in range(40))
    return f"<script>{padding}{assign} = {blob};</script>"


def test_listing_jsonld_is_kept() -> None:
    digest, blobs = extract_embedded_data(page(ld(LISTING_LD)))
    assert blobs == 1
    assert "Maple Court" in digest and "PostalAddress" in digest


def test_boilerplate_only_jsonld_is_dropped() -> None:
    crumbs = {"@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": 1}]}
    digest, blobs = extract_embedded_data(page(ld(crumbs)))
    assert blobs == 0 and digest == ""


def test_state_blob_signal_subtree_is_kept_and_noise_dropped() -> None:
    digest, blobs = extract_embedded_data(page(state_script(FLOORPLAN_STATE)))
    assert blobs == 1
    assert '"priceRange":{"min":1443' in digest.replace(" ", "")
    assert "abTestingData" not in digest and "featureMap" not in digest


def test_similar_listing_contamination_is_dropped() -> None:
    """`similar` carries another property's floor plans — drop beats keep."""
    digest, _ = extract_embedded_data(page(state_script(FLOORPLAN_STATE)))
    assert "OTHER" not in digest and "999" not in digest


def test_media_keys_and_url_values_are_scrubbed_from_kept_subtrees() -> None:
    state = {
        "floorPlans": [
            {
                "name": "A1",
                "priceLow": 1200,
                "imageFloorPlan": {"url": "https://cdn.example/fp.png"},
                "tourLink": "https://cdn.example/tour",
                "brochure": "https://cdn.example/a1.pdf",
            }
        ]
    }
    digest, _ = extract_embedded_data(page(state_script(state)))
    assert "1200" in digest
    assert "cdn.example" not in digest and "imageFloorPlan" not in digest


def test_js_object_literals_and_minified_js_are_ignored() -> None:
    js = "<script>" + "window.junk = {unquoted: keys, are: not_json};" * 30 + "</script>"
    digest, blobs = extract_embedded_data(page(js))
    assert blobs == 0 and digest == ""


def test_duplicate_blobs_are_deduped() -> None:
    _digest, blobs = extract_embedded_data(page(ld(LISTING_LD), ld(LISTING_LD)))
    assert blobs == 1


def test_digest_is_capped_at_budget() -> None:
    huge = {
        "floorPlans": [
            {"name": f"Plan {i}", "priceLow": 1000 + i, "description": "x" * 400}
            for i in range(EMBEDDED_DATA_MAX_CHARS // 400)
        ]
    }
    digest, _ = extract_embedded_data(page(state_script(huge)))
    assert len(digest) <= EMBEDDED_DATA_MAX_CHARS + len("…[embedded data truncated]")
    assert digest.endswith("…[embedded data truncated]")


def test_garbage_html_does_not_raise() -> None:
    assert extract_embedded_data("") == ("", 0)
    assert extract_embedded_data("<<<not html>>>")[1] == 0


def test_cleaner_appends_digest_under_marker() -> None:
    html = page(ld(LISTING_LD), body_text="Welcome home. " * 60)
    cleaned = clean_html(html)
    assert EMBEDDED_DATA_MARKER in cleaned.text
    assert cleaned.embedded_blobs == 1
    assert cleaned.text.index("Welcome home") < cleaned.text.index(EMBEDDED_DATA_MARKER)


def test_pages_without_embedded_data_are_unchanged() -> None:
    cleaned = clean_html(page(body_text="Two bedroom apartments in Detroit. " * 40))
    assert EMBEDDED_DATA_MARKER not in cleaned.text
    assert cleaned.embedded_blobs == 0


def _result(body: str) -> FetchResult:
    return FetchResult(
        url="https://example.com/listing",
        final_url="https://example.com/listing",
        status_code=200,
        body=body,
        tier=1,
    )


def test_js_shell_with_data_bearing_state_blob_is_success() -> None:
    """The zumper/padmapper case: empty DOM, script-heavy body, but the state
    blob carries the listing — positive content outranks the shell heuristic."""
    state = {
        "listing": {
            "name": "Maple Court",
            "address": {"streetAddress": "1 Maple St", "postalCode": "48187"},
            "floorPlans": [
                {"name": f"Plan {i}", "bedCount": 1 + i % 3, "priceLow": 1400 + i, "sqFt": 700 + i}
                for i in range(20)
            ],
        }
    }
    body = page(state_script(state), "<script>" + "var pad=1;" * 2000 + "</script>")
    assert classify(_result(body), clean_html(body)) is FetchOutcome.SUCCESS


def test_true_js_shell_still_classifies_shell() -> None:
    body = page("<script>" + "var pad=1;" * 2000 + "</script>")
    assert classify(_result(body), clean_html(body)) is FetchOutcome.SHELL
