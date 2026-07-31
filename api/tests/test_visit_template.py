"""The Visit Checklist template is generated, never hand-edited (VC-1).

`api/src/manzil_api/visits/template.py` is the canonical source; the migration
carries generated SQL. These tests are what stops the two drifting: if someone
edits the module without regenerating, or edits the migration by hand, the
committed SQL stops matching and this fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from manzil_api.visits.template import (
    TEMPLATE,
    TEMPLATE_VERSION,
    generate_template_sql,
    sections,
    validate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SEEDING_MIGRATION = REPO_ROOT / "supabase" / "migrations" / "20260817000000_visits.sql"


def test_template_is_internally_consistent() -> None:
    validate()


def test_committed_migration_matches_the_module() -> None:
    """The seeding migration embeds `generate_template_sql()` verbatim."""
    migration = SEEDING_MIGRATION.read_text()
    assert generate_template_sql() in migration, (
        "supabase/migrations/20260817000000_visits.sql no longer matches "
        "api/src/manzil_api/visits/template.py. Regenerate the seed block rather "
        "than hand-editing the migration; a new template version needs its own "
        "migration, not an edit to this one."
    )


def test_seeding_migration_remains_frozen_history() -> None:
    """A future template version gets a new migration; this one stays at v1.

    Same posture as the frozen scoped-Catalog migration tests: an applied
    migration is history, so changing it in place would leave every existing
    database disagreeing with the file that supposedly produced it.
    """
    migration = SEEDING_MIGRATION.read_text()
    assert "insert into visit_template_items (" in migration
    assert TEMPLATE_VERSION == 1
    # Every seeded row in this migration is version 1.
    seed_rows = [line for line in migration.splitlines() if line.startswith("    ('")]
    assert seed_rows, "seed block missing"
    assert all(", 1, '" in row for row in seed_rows)
    assert len(seed_rows) == len(TEMPLATE)


def test_keys_are_stable_identifiers() -> None:
    """Keys are the join identity for every stored answer, so they are code-shaped."""
    for item in TEMPLATE:
        assert item.key == item.key.lower()
        assert item.key.replace("_", "").isalnum(), item.key
        assert not item.key.startswith("_") and not item.key.endswith("_")


def test_exactly_the_twelve_critical_questions() -> None:
    """`docs/apartment-tour-checklist.md` §1 names twelve. Drift here means the
    Quick tier and the "N critical" counter start lying."""
    critical = [item for item in TEMPLATE if item.is_critical]
    assert len(critical) == 12
    # A critical item must be answerable during the tour, so it is in Quick.
    assert all(item.tier == "quick" for item in critical)


def test_scope_split_of_the_verdict_section() -> None:
    """DESIGN §9.7 / R10: §21 is the one genuinely mixed section and must split."""
    unit_side = {i.key for i in TEMPLATE if i.section_key == "verdict_unit"}
    property_side = {i.key for i in TEMPLATE if i.section_key == "verdict_property"}
    assert unit_side and property_side
    assert all(i.scope == "unit" for i in TEMPLATE if i.section_key == "verdict_unit")
    assert all(i.scope == "property" for i in TEMPLATE if i.section_key == "verdict_property")
    # The four you would answer identically for every unit live on the property side.
    assert {"verdict_safety", "verdict_location_commute", "verdict_management"} <= property_side
    assert {"verdict_price_value", "verdict_noise", "verdict_light"} <= unit_side


def test_every_tier_is_populated_and_quick_is_a_real_subset() -> None:
    """The depth dial is only useful if the tiers actually differ in size."""
    by_tier = {
        tier: [i for i in TEMPLATE if i.tier == tier] for tier in ("quick", "standard", "thorough")
    }
    assert all(items for items in by_tier.values())
    assert len(by_tier["quick"]) < len(TEMPLATE)


def test_sections_are_contiguous_and_ordered() -> None:
    keys = sections()
    assert len(keys) == len(set(keys)), "a section appears in two separate runs"
    assert keys[0] == "essentials", "the ten-minute pass comes first"
    assert keys[-2:] == ("verdict_unit", "verdict_property")


@pytest.mark.parametrize("kind", ["fact", "check", "question", "impression"])
def test_every_kind_is_used(kind: str) -> None:
    assert any(item.kind == kind for item in TEMPLATE)


def test_generated_sql_escapes_quotes() -> None:
    """At least one label contains an apostrophe; a naive generator would break
    the migration, so assert the doubling rather than trusting it."""
    assert any("'" in item.label for item in TEMPLATE)
    sql = generate_template_sql()
    assert "''" in sql
