"""Rescore stage (P1-6, DESIGN §9.3-9.6): hunt-level deterministic re-score.

No URL, no LLM — resolve effective values from persisted extractions and
overrides, apply the hunt's `min_confidence` threshold, score each scorable
floor plan via the shared engine, upsert `scores`.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from manzil_shared.catalog import BOOLEAN_PRESENCE_KEYS, SCOPED_UNIT_CLAIM_KEYS
from manzil_shared.models import Confidence, FloorPlan, RubricCriterion
from manzil_shared.scoped_facts import resolve_effective_value, resolve_effective_values
from manzil_shared.scoring.engine import criterion_key, score, select_display_score

from manzil_worker.enrich.utility_baselines import (
    BaselineSet,
    baselines_for_property_locality,
    region_estimate_note,
)
from manzil_worker.scoped_facts import (
    load_current_extractions,
    load_current_overrides,
    property_values,
)
from manzil_worker.stages.pet_costs import (
    MANDATORY_FEE_SLOTS,
    beds_bucket,
    compose_all_in,
    pet_monthly,
    slot_for_fee,
)

if True:  # TYPE_CHECKING without import cycle
    import asyncpg

log = structlog.get_logger()


async def _latest_pet_rents(
    conn: asyncpg.Connection, hunt_listing_id: UUID
) -> tuple[float | None, float | None, float | None]:
    """Per-pet rents from the listing's fee_checklist (§9.5 v1): the extracted
    `pet_rent_cat`/`pet_rent_dog`/`pet_rent` slots, with any human `manual`
    amount overriding — so a manual fee edit is genuinely rescore-effective. An
    explicitly `unknown` slot contributes nothing. Returns (cat, dog, generic)."""
    rows = await conn.fetch(
        """
        select fee_slot, amount from fee_checklist
        where hunt_listing_id = $1
          and fee_slot in ('pet_rent_cat', 'pet_rent_dog', 'pet_rent')
          and value_state <> 'unknown'
        """,
        hunt_listing_id,
    )
    amounts = {
        row["fee_slot"]: (float(row["amount"]) if row["amount"] is not None else None)
        for row in rows
    }
    return (
        amounts.get("pet_rent_cat"),
        amounts.get("pet_rent_dog"),
        amounts.get("pet_rent"),
    )


def _composition_json(composition: Any, all_in_override: Any) -> dict[str, Any] | None:
    """The display-metadata JSON for one plan's composition. A live
    all_in_monthly override replaces the total and marks the plan overridden
    (§9.6) — components stay as composed, so the drawer can still show what
    the machine would have said."""
    if composition is None:
        return None
    out: dict[str, Any] = composition.to_json()
    if all_in_override is not None:
        try:
            out["total"] = float(all_in_override)
        except (TypeError, ValueError):
            return out  # non-numeric override never fabricates a total
        out["overridden"] = True
    return out


def _conservative_rent(rent_min: Decimal | None, rent_max: Decimal | None) -> float | None:
    if rent_max is not None:
        return float(rent_max)
    if rent_min is not None:
        return float(rent_min)
    return None


async def _mandatory_fees(
    conn: asyncpg.Connection,
    hunt_listing_id: UUID,
    catalog_ext: dict[str, tuple[Any, Confidence]],
) -> list[tuple[str, float]]:
    """§9.5 mandatory-fee components at rescore: checklist slot amounts (manual
    entries naturally win — projection never clobbers them) + the extracted fees
    that map to no slot (they live only on the `mandatory_fees` extraction)."""
    rows = await conn.fetch(
        """
        select fee_slot, amount from fee_checklist
        where hunt_listing_id = $1
          and fee_slot = any($2::text[])
          and value_state <> 'unknown'
          and amount is not null
        """,
        hunt_listing_id,
        list(MANDATORY_FEE_SLOTS),
    )
    fees = [(row["fee_slot"], float(row["amount"])) for row in rows]
    extracted = catalog_ext.get("mandatory_fees")
    if extracted is not None and isinstance(extracted[0], list):
        for entry in extracted[0]:
            name = entry.get("name")
            amount = entry.get("amount_monthly")
            if name and amount is not None and slot_for_fee(name) is None:
                fees.append((name, float(amount)))
    return fees


async def rescore_hunt(
    conn: asyncpg.Connection,
    *,
    hunt_id: UUID,
    rubric: list[RubricCriterion],
    rubric_version: int,
    min_confidence: Confidence,
    cats: int = 0,
    dogs: int = 0,
    cost_estimate_mode: str = "conservative",
    occupants: int = 1,
) -> int:
    """Rescore every active listing on the hunt. Returns the number of score rows upserted."""
    listings = await conn.fetch(
        """
        select hl.id, hl.property_id, p.city, p.state, p.county from hunt_listings hl
        join properties p on p.id = hl.property_id
        where hl.hunt_id = $1 and hl.status = 'active'
        """,
        hunt_id,
    )
    upserted = 0
    for listing in listings:
        listing_id: UUID = listing["id"]
        property_id: UUID = listing["property_id"]
        city: str | None = listing["city"]
        state_code: str | None = listing["state"]
        county: str | None = listing["county"]
        current_extractions = await load_current_extractions(
            conn, property_id=property_id, hunt_id=hunt_id
        )
        current_overrides = await load_current_overrides(conn, hunt_listing_id=listing_id)
        catalog_ext = property_values(current_extractions)
        rubric_keys = [criterion_key(criterion) for criterion in rubric]
        cat_rent, dog_rent, generic_rent = await _latest_pet_rents(conn, listing_id)
        pet_add = pet_monthly(
            cats=cats,
            dogs=dogs,
            cat_rent=cat_rent,
            dog_rent=dog_rent,
            generic_rent=generic_rent,
        )
        # §9.5 P3-9 composition inputs, from the same persisted rows the ingest
        # projection writes — the two paths never drift.
        fees = await _mandatory_fees(conn, listing_id, catalog_ext)
        included_ext = catalog_ext.get("utilities_included")
        included = included_ext[0] if included_ext is not None else None
        baselines_by_bucket: dict[int, BaselineSet | None] = {}

        floor_plans = await conn.fetch(
            "select * from floor_plans where property_id = $1 and is_current",
            property_id,
        )
        breakdown_objs = []
        compositions = []
        for fp in floor_plans:
            if fp["beds"] is None or fp["baths"] is None:
                continue
            floor_plan = FloorPlan(
                property_id=property_id,
                source_id=fp["source_id"],
                plan_name=fp["plan_name"],
                beds=fp["beds"],
                baths=fp["baths"],
                unit_types=json.loads(fp["unit_types"] or "[]"),
                sqft_min=fp["sqft_min"],
                sqft_max=fp["sqft_max"],
                rent_min=fp["rent_min"],
                rent_max=fp["rent_max"],
                deposit=fp["deposit"],
                availability_date=fp["availability_date"],
            )
            values = resolve_effective_values(
                criterion_keys=rubric_keys,
                floor_plan_id=fp["id"],
                extractions=current_extractions,
                overrides=current_overrides,
                min_confidence=min_confidence,
                presence_like_keys=SCOPED_UNIT_CLAIM_KEYS,
                boolean_presence_keys=BOOLEAN_PRESENCE_KEYS,
            )
            heating_value = resolve_effective_value(
                criterion_key="heating_type",
                floor_plan_id=fp["id"],
                extractions=current_extractions,
                min_confidence=min_confidence,
                presence_like=True,
                boolean_presence=False,
            )
            heating = heating_value if heating_value in {"gas", "electric"} else None
            rent = _conservative_rent(fp["rent_min"], fp["rent_max"])
            composition = None
            # A live all_in_monthly override beats the composition (§9.6, §20
            # 2026-07-18): the scored value is the human's figure (already in
            # effective values), and the display plan is marked overridden.
            all_in_override = resolve_effective_value(
                criterion_key="all_in_monthly",
                floor_plan_id=fp["id"],
                extractions=(),
                overrides=current_overrides,
                min_confidence=min_confidence,
            )
            if rent is not None:
                bucket = beds_bucket(fp["beds"])
                if bucket not in baselines_by_bucket:
                    baselines_by_bucket[bucket] = (
                        await baselines_for_property_locality(
                            conn,
                            city=city,
                            state=state_code,
                            county=county,
                            bucket=bucket,
                        )
                        if state_code is not None
                        else None
                    )
                baseline_set = baselines_by_bucket[bucket]
                composition = compose_all_in(
                    rent=rent,
                    pet_add=pet_add,
                    mandatory_fees=fees,
                    included=included,
                    heating=heating,
                    baselines=baseline_set.values if baseline_set else None,
                    baseline_scope_note=(
                        region_estimate_note(baseline_set.region) if baseline_set else None
                    ),
                    mode=cost_estimate_mode,
                    occupants=occupants,
                    beds=fp["beds"],
                )
                if all_in_override is None and composition.total is not None:
                    values["all_in_monthly"] = composition.total
            breakdown_obj = score(rubric, values, floor_plan, rubric_version=rubric_version)
            breakdown_objs.append(breakdown_obj)
            compositions.append(_composition_json(composition, all_in_override))
            breakdown = breakdown_obj.to_contract()
            await conn.execute(
                """
                insert into scores
                    (hunt_listing_id, floor_plan_id, total, breakdown, rubric_version,
                     all_in_components)
                values ($1, $2, $3, $4::jsonb, $5, $6::jsonb)
                on conflict (hunt_listing_id, floor_plan_id) do update set
                    total = excluded.total,
                    breakdown = excluded.breakdown,
                    rubric_version = excluded.rubric_version,
                    all_in_components = excluded.all_in_components,
                    computed_at = now()
                """,
                listing_id,
                fp["id"],
                Decimal(str(breakdown["total"])),
                json.dumps(breakdown),
                rubric_version,
                json.dumps(compositions[-1]) if compositions[-1] is not None else None,
            )
            upserted += 1
        if breakdown_objs:
            # Same display selection as SCORE: the display plan's composition
            # detail lands on hunt_listings.all_in_components (P3-9).
            display = compositions[select_display_score(breakdown_objs)]
            await conn.execute(
                "update hunt_listings set all_in_components = $2::jsonb where id = $1",
                listing_id,
                json.dumps(display) if display is not None else None,
            )
    log.info("rescore_hunt_complete", hunt_id=str(hunt_id), score_rows=upserted)
    return upserted
