"""P0-2 done-when: the catalog round-trips python -> SQL -> loaded.

The loader here is a literal parser for the generated seed.sql: it reads the
VALUES rows back into `CatalogEntry` models and asserts exact equality with
the source catalog, so any serialization drift (quoting, jsonb shape, column
order) fails loudly. Loading into live Postgres is exercised by P0-4's
`supabase db reset` once migration 0001 creates the table.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from manzil_shared.catalog import (
    _COLUMNS,
    _JSONB_COLUMNS,
    CATALOG,
    generate_catalog_sync_sql,
    generate_seed_sql,
)
from manzil_shared.models import CatalogEntry

REPO_ROOT = Path(__file__).resolve().parents[2]


def _split_row(row: str) -> list[str]:
    """Split one `(...)` values row on top-level commas, honoring '' escapes."""
    fields: list[str] = []
    current: list[str] = []
    in_string = False
    i = 0
    while i < len(row):
        ch = row[i]
        if in_string:
            if ch == "'":
                if i + 1 < len(row) and row[i + 1] == "'":  # escaped quote
                    current.append("''")
                    i += 2
                    continue
                in_string = False
            current.append(ch)
        elif ch == "'":
            in_string = True
            current.append(ch)
        elif ch == ",":
            fields.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    fields.append("".join(current).strip())
    return fields


def _load_literal(column: str, field: str) -> Any:
    if field == "null":
        return None
    field = field.removesuffix("::jsonb")
    assert field.startswith("'") and field.endswith("'"), field
    text = field[1:-1].replace("''", "'")
    if column in _JSONB_COLUMNS:
        return json.loads(text)
    return text


def parse_seed_sql(sql: str) -> list[CatalogEntry]:
    values_block = sql.split("values\n", 1)[1].split("\non conflict", 1)[0]
    entries: list[CatalogEntry] = []
    for line in values_block.splitlines():
        row = line.strip().removesuffix(",")
        assert row.startswith("(") and row.endswith(")"), row
        fields = _split_row(row[1:-1])
        assert len(fields) == len(_COLUMNS), fields
        data = {col: _load_literal(col, field) for col, field in zip(_COLUMNS, fields, strict=True)}
        entries.append(CatalogEntry.model_validate(data))
    return entries


def test_catalog_contains_the_approved_p3_sc3_tranche() -> None:
    keys = [entry.key for entry in CATALOG]
    assert len(keys) == len(set(keys)) == 32
    assert keys == [
        "beds",
        "baths",
        "sqft",
        "patio_balcony",
        "private_entry",
        "in_unit_laundry",
        "pets_policy",
        "all_in_monthly",
        "security_deposit",
        "availability_date",
        "kitchen_quality",
        "flooring_quality",
        "parking",
        "cooling",
        "dishwasher",
        "min_lease_months",
        "grocery_proximity",
        "management_reviews",
        "location_safety",
        "pool",
        "fitness_center",
        "clubhouse",
        "emergency_maintenance",
        "maintenance_on_site",
        "management_on_site",
        "online_payments",
        "online_maintenance_requests",
        "package_handling",
        "smoking_policy",
        "property_types",
        "unit_types",
        "internet_readiness",
    ]

    by_key = {entry.key: entry for entry in CATALOG}
    assert by_key["pool"].category.value == "property"
    assert by_key["pool"].fact_scope.value == "property"
    assert by_key["pool"].escalation_policy.value == "available_sources_only"
    assert by_key["pool"].conflict_policy.value == "verified_positive_preferred"
    assert by_key["smoking_policy"].escalation_policy.value == "decision_relevant"
    assert by_key["unit_types"].fact_scope.value == "floor_plan"
    assert by_key["property_types"].value_schema["uniqueItems"] is True
    assert by_key["property_types"].default_options[0].match.op.value == "contains_any"


def test_seed_sql_round_trips() -> None:
    assert parse_seed_sql(generate_seed_sql()) == list(CATALOG)


def test_committed_seed_sql_is_current() -> None:
    """supabase/seed.sql is generated, never hand-edited: regenerating must be a no-op."""
    committed = (REPO_ROOT / "supabase" / "seed.sql").read_text()
    assert committed == generate_seed_sql(), (
        "supabase/seed.sql is stale — regenerate: "
        "uv run --package manzil-shared python -m manzil_shared.catalog"
    )


def test_p3_sc3_catalog_sync_is_generated_from_catalog() -> None:
    keys = [entry.key for entry in CATALOG[-13:]]
    migration = (
        REPO_ROOT / "supabase" / "migrations" / "20260802000000_catalog_sync_p3_sc3.sql"
    ).read_text()
    assert migration == generate_catalog_sync_sql(*keys)


def test_beds_entry_matches_pinned_contract() -> None:
    """The complete `beds` entry is pinned in DESIGN §8.2 — do not reshape."""
    beds = CATALOG[0]
    dumped = beds.model_dump(mode="json", exclude_none=True)
    dumped["default_options"] = [
        opt.model_dump(mode="json", exclude_none=True) for opt in beds.default_options
    ]
    assert dumped == {
        "key": "beds",
        "label": "Number of bedrooms",
        "category": "unit",
        "domain": "rent",
        "fact_scope": "floor_plan",
        "value_schema": {"type": "integer", "minimum": 0, "maximum": 5},
        "default_options": [
            {"match": {"op": "eq", "value": 2}, "delta": 0.5},
            {"match": {"op": "eq", "value": 1}, "delta": 0.0},
            {"match": {"op": "eq", "value": 0}, "delta": -0.5},
        ],
        "extraction_hint": "Count distinct bedrooms; a studio is 0.",
        "refresh_class": "listing_details",
        "escalation_policy": "decision_relevant",
        "conflict_policy": "standard_ladder",
    }
