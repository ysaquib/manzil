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
MIGRATIONS = REPO_ROOT / "supabase" / "migrations"

# One seeding migration per template version. The module only ever describes the
# *current* version, so older entries here are checked structurally rather than
# against the module — that is what freezing means.
SEEDING_MIGRATIONS = {
    1: MIGRATIONS / "20260817000000_visits.sql",
    2: MIGRATIONS / "20260826000000_visit_template_v2.sql",
}

# Row counts of superseded versions, frozen at the point they were superseded.
FROZEN_ROW_COUNTS = {1: 248}


def test_template_is_internally_consistent() -> None:
    validate()


def test_committed_migration_matches_the_module() -> None:
    """The current version's migration embeds `generate_template_sql()` verbatim."""
    path = SEEDING_MIGRATIONS[TEMPLATE_VERSION]
    migration = path.read_text()
    assert generate_template_sql() in migration, (
        f"{path.name} no longer matches api/src/manzil_api/visits/template.py. "
        "Regenerate the seed block rather than hand-editing the migration; a new "
        "template version needs its own migration, not an edit to this one."
    )


def test_every_version_has_its_own_migration() -> None:
    """A version with no migration is a version no database has."""
    assert TEMPLATE_VERSION in SEEDING_MIGRATIONS
    assert set(SEEDING_MIGRATIONS) == set(range(1, TEMPLATE_VERSION + 1))
    for path in SEEDING_MIGRATIONS.values():
        assert path.exists(), path


@pytest.mark.parametrize("version", sorted(FROZEN_ROW_COUNTS))
def test_superseded_migrations_remain_frozen_history(version: int) -> None:
    """A superseded seeding migration is never edited again.

    Same posture as the frozen scoped-Catalog migration tests: an applied
    migration is history, so changing it in place would leave every existing
    database disagreeing with the file that supposedly produced it. The module
    no longer describes these rows, so the assertion is structural: every row
    still carries its own version, and there are still exactly as many as there
    were when the version was frozen.
    """
    migration = SEEDING_MIGRATIONS[version].read_text()
    assert "insert into visit_template_items (" in migration
    seed_rows = [line for line in migration.splitlines() if line.startswith("    ('")]
    assert seed_rows, "seed block missing"
    assert all(f", {version}, '" in row for row in seed_rows)
    assert len(seed_rows) == FROZEN_ROW_COUNTS[version]


def test_current_version_seeds_every_item() -> None:
    migration = SEEDING_MIGRATIONS[TEMPLATE_VERSION].read_text()
    seed_rows = [line for line in migration.splitlines() if line.startswith("    ('")]
    assert len(seed_rows) == len(TEMPLATE)
    assert all(f", {TEMPLATE_VERSION}, '" in row for row in seed_rows)


def test_the_actual_unit_question_offers_a_middle_answer() -> None:
    """VC-11: the same plan two floors down is neither `actual` nor `model`."""
    item = next(i for i in TEMPLATE if i.key == "sweep_actual_unit")
    assert item.is_critical
    assert item.value_schema["options"] == ["actual", "model", "similar"]


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
