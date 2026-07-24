"""US locality parsing — Google components + strict original-address fallback."""

from __future__ import annotations

from manzil_worker.enrich.locality import parse_us_locality


def _components(**kwargs: list[dict]) -> list[dict]:
    out: list[dict] = []
    for kind, entries in kwargs.items():
        for entry in entries:
            out.append({"long_name": entry[0], "short_name": entry[1], "types": [kind]})
    return out


def test_detroit_without_locality_uses_postal_city() -> None:
    components = _components(
        country=[("United States", "US")],
        administrative_area_level_1=[("Michigan", "MI")],
        administrative_area_level_2=[("Wayne County", "Wayne")],
        administrative_area_level_3=[("Detroit Township", "Detroit")],
    )
    locality = parse_us_locality(components, "120 Main St, Detroit, MI 48201")
    assert locality.city == "Detroit"
    assert locality.state == "MI"
    assert locality.county == "Wayne County"


def test_full_state_name_and_zip_plus_four() -> None:
    components = _components(country=[("United States", "US")])
    locality = parse_us_locality(
        components,
        "120 Main St, Detroit, Michigan 48201-1234, USA",
    )
    assert locality.city == "Detroit"
    assert locality.state == "MI"


def test_google_locality_wins_over_conflicting_address() -> None:
    components = _components(
        country=[("United States", "US")],
        locality=[("Detroit", "Detroit")],
        administrative_area_level_1=[("Michigan", "MI")],
    )
    locality = parse_us_locality(components, "120 Main St, Detroit, MI 48201")
    assert locality.city == "Detroit"
    assert locality.state == "MI"


def test_township_without_postal_city_leaves_city_null() -> None:
    components = _components(
        country=[("United States", "US")],
        administrative_area_level_1=[("Michigan", "MI")],
        administrative_area_level_2=[("Wayne County", "Wayne")],
        administrative_area_level_3=[("Detroit Township", "Detroit")],
    )
    locality = parse_us_locality(components, "120 Main St")
    assert locality.city is None
    assert locality.state == "MI"
    assert locality.county == "Wayne County"


def test_invalid_state_token_is_rejected() -> None:
    components = _components(country=[("United States", "US")])
    locality = parse_us_locality(components, "120 Main St, Detroit, ZZ 48201")
    assert locality.city is None
    assert locality.state is None


def test_non_us_result_does_not_apply_us_address_fallback() -> None:
    components = _components(
        country=[("Canada", "CA")],
        administrative_area_level_1=[("Ontario", "ON")],
        locality=[("Toronto", "Toronto")],
    )
    locality = parse_us_locality(components, "120 Main St, Detroit, MI 48201")
    assert locality.city == "Toronto"
    assert locality.state is None


def test_component_order_is_immaterial() -> None:
    first = _components(
        country=[("United States", "US")],
        locality=[("Detroit", "Detroit")],
        administrative_area_level_1=[("Michigan", "MI")],
        administrative_area_level_2=[("Wayne County", "Wayne")],
    )
    second = list(reversed(first))
    address = "120 Main St, Detroit, MI 48201"
    assert parse_us_locality(first, address) == parse_us_locality(second, address)
