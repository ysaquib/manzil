"""Rescore stage (P1-6, DESIGN §9.3-9.6): hunt-level deterministic re-score.

No URL, no LLM — resolve effective values from persisted extractions and
overrides, apply the hunt's `min_confidence` threshold, score each scorable
floor plan via the shared engine, upsert `scores`.
"""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from manzil_shared.catalog import (
    BOOLEAN_PRESENCE_KEYS,
    CONFIRMED_SCOPE_ONLY_KEYS,
    PRESENCE_LIKE_KEYS,
)
from manzil_shared.models import Confidence, FloorPlan, RubricCriterion
from manzil_shared.scoped_facts import (
    resolve_effective_facts,
    resolve_effective_value,
    scoring_values_for_policy,
)
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
from manzil_worker.stages.move_in import (
    Household,
    MoveInCharge,
    basis_multiplier,
    charge_from_extracted_fee,
    compose_move_in,
    default_required,
)
from manzil_worker.stages.pet_costs import (
    CHECKLIST_FEE_SLOTS,
    MANDATORY_FEE_SLOTS,
    ONE_TIME_FEE_SLOTS,
    beds_bucket,
    compose_all_in,
    pet_monthly,
    slot_for_fee,
    slot_for_one_time_fee,
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
    utility_amount_keys: frozenset[str] = frozenset(),
) -> list[tuple[str, float]]:
    """§9.5 mandatory-fee components at rescore: checklist slot amounts (manual
    entries naturally win — projection never clobbers them) + the extracted fees
    that map to no slot (they live only on the `mandatory_fees` extraction).

    A slot the user has explicitly un-counted drops out of the all-in entirely
    (§9.5, the consolidated Cost & fees surface): the row still displays with
    its amount, struck through, but a charge nobody is going to pay must not
    inflate the scored figure. `counted` NULL is the machine default, counted.
    """
    rows = await conn.fetch(
        """
        select fee_slot, amount from fee_checklist
        where hunt_listing_id = $1
          and fee_slot = any($2::text[])
          and value_state <> 'unknown'
          and amount is not null
          and coalesce(counted, true)
        """,
        hunt_listing_id,
        list(MANDATORY_FEE_SLOTS),
    )
    covered_slots = {
        "water_sewer" if key in {"water", "sewer"} else "valet_trash"
        for key in utility_amount_keys
        if key in {"water", "sewer", "trash"}
    }
    fees = [
        (row["fee_slot"], float(row["amount"]))
        for row in rows
        if row["fee_slot"] not in covered_slots
    ]
    fee_names = {name for name, _ in fees}
    # Unmapped mandatory fees a human corrected inline land on fee_checklist under
    # the page's own fee name — they must compose like the extraction row would.
    custom_rows = await conn.fetch(
        """
        select fee_slot, amount from fee_checklist
        where hunt_listing_id = $1
          and not (fee_slot = any($2::text[]))
          and value_state <> 'unknown'
          and amount is not null
          and coalesce(counted, true)
        """,
        hunt_listing_id,
        list(CHECKLIST_FEE_SLOTS),
    )
    for row in custom_rows:
        slot = row["fee_slot"]
        if slot in fee_names:
            continue
        fees.append((slot, float(row["amount"])))
        fee_names.add(slot)
    extracted = catalog_ext.get("mandatory_fees")
    if extracted is not None and isinstance(extracted[0], list):
        for entry in extracted[0]:
            name = entry.get("name")
            amount = entry.get("amount_monthly")
            slot = slot_for_fee(name or "")
            if name and amount is not None and slot is None and name not in fee_names:
                fees.append((name, float(amount)))
                fee_names.add(name)
    return fees


async def _effective_utilities_included(
    conn: asyncpg.Connection,
    hunt_listing_id: UUID,
    extracted: Any,
) -> tuple[list[str] | None, dict[str, float], frozenset[str]]:
    """Merge individual manual utility decisions onto the extracted list.

    A NULL current override is a revert tombstone, so it intentionally has no
    effect and the underlying extracted fact shows through again.  Returning
    None preserves the conservative "page silent" branch when no human has
    made a decision.
    """
    rows = await conn.fetch(
        """
        select utility, included, monthly_amount from current_utility_overrides
        where hunt_listing_id = $1
        """,
        hunt_listing_id,
    )
    active = [
        row for row in rows if row["included"] is not None or row["monthly_amount"] is not None
    ]
    amounts = {
        row["utility"]: float(row["monthly_amount"])
        for row in active
        if row["monthly_amount"] is not None
    }
    fee_replacements = frozenset(amounts) | frozenset(
        row["utility"] for row in active if row["included"] is True
    )
    if extracted is None and not active:
        return None, amounts, fee_replacements
    values = set(extracted) if isinstance(extracted, list) else set()
    for row in active:
        if row["included"] is True:
            values.add(row["utility"])
        elif row["included"] is False:
            values.discard(row["utility"])
    return sorted(values), amounts, fee_replacements


async def _move_in_charges(
    conn: asyncpg.Connection,
    hunt_listing_id: UUID,
    catalog_ext: dict[str, tuple[Any, Confidence]],
    household: Household,
) -> list[MoveInCharge]:
    """The §9.5 P3-SC8 one-time ledger for this Listing and household.

    Each standard slot merges three layers: the `one_time_fees` extraction
    (basis + stated refundability), the checklist amount (a manual entry beats
    the extracted one), and the human decisions — required, refundable,
    credited portion, counted. Extracted charges that map to no standard slot
    still count; they just have no checklist affordance.
    """
    extracted = catalog_ext.get("one_time_fees")
    fees: list[dict[str, Any]] = []
    if extracted is not None and isinstance(extracted[0], list):
        fees = [fee for fee in extracted[0] if isinstance(fee, dict)]
    by_slot: dict[str, dict[str, Any]] = {}
    unslotted: list[dict[str, Any]] = []
    for fee in fees:
        slot = slot_for_one_time_fee(str(fee.get("name") or ""))
        if slot is None:
            unslotted.append(fee)
        elif slot not in by_slot:
            by_slot[slot] = fee

    rows = await conn.fetch(
        """
        select fee_slot, amount, value_state, counted, required, refundable,
               credited_amount
        from fee_checklist
        where hunt_listing_id = $1 and fee_slot = any($2::text[])
        """,
        hunt_listing_id,
        list(ONE_TIME_FEE_SLOTS),
    )
    persisted = {row["fee_slot"]: row for row in rows}

    charges: list[MoveInCharge] = []
    for slot in ONE_TIME_FEE_SLOTS:
        row = persisted.get(slot)
        fee = by_slot.get(slot)
        if row is None and fee is None:
            continue
        basis = str(fee.get("basis")) if fee and fee.get("basis") is not None else None
        multiplier = basis_multiplier(basis, household)
        stated: float | None = None
        if row is not None and row["amount"] is not None and row["value_state"] != "unknown":
            stated = float(row["amount"])
        elif fee is not None and isinstance(fee.get("amount"), int | float):
            stated = float(fee["amount"])
        amount = round(stated * multiplier, 2) if stated is not None else None

        required = default_required(slot, household)
        if row is not None and row["required"] is not None:
            required = bool(row["required"])
        refundable: bool | None = None
        if fee is not None and isinstance(fee.get("refundable"), bool):
            refundable = bool(fee["refundable"])
        if row is not None and row["refundable"] is not None:
            refundable = bool(row["refundable"])
        credited = (
            float(row["credited_amount"])
            if row is not None and row["credited_amount"] is not None
            else 0.0
        )
        counted = required
        if row is not None and row["counted"] is not None:
            counted = bool(row["counted"])
        note = None
        if multiplier != 1 and stated is not None:
            unit = "person" if basis == "per_person" else "pet"
            note = f"${stated:g} per {unit} x {multiplier}"
        charges.append(
            MoveInCharge(
                name=slot,
                amount=amount,
                tag="actual" if amount is not None else "unknown",
                required=required,
                refundable=refundable,
                credited=min(credited, amount) if amount is not None else 0.0,
                counted=counted,
                note=note,
            )
        )
    charges += [charge_from_extracted_fee(fee, household) for fee in unslotted]
    return charges


async def _rescore_listings(
    conn: asyncpg.Connection,
    *,
    hunt_id: UUID,
    listings: list[asyncpg.Record],
    rubric: list[RubricCriterion],
    rubric_version: int,
    min_confidence: Confidence,
    min_vision_confidence: Confidence = Confidence.LOW,
    cats: int = 0,
    dogs: int = 0,
    cost_estimate_mode: str = "conservative",
    occupants: int = 1,
    generalized_vision_policy: str = "full_rubric",
) -> int:
    """Rescore the supplied active Listings from persisted current facts."""
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
        included_ext = catalog_ext.get("utilities_included")
        included, utility_amounts, utility_fee_replacements = await _effective_utilities_included(
            conn,
            listing_id,
            included_ext[0] if included_ext is not None else None,
        )
        fees = await _mandatory_fees(
            conn,
            listing_id,
            catalog_ext,
            utility_fee_replacements,
        )
        household = Household(occupants=occupants, cats=cats, dogs=dogs)
        one_time_charges = await _move_in_charges(conn, listing_id, catalog_ext, household)
        baselines_by_bucket: dict[int, BaselineSet | None] = {}

        floor_plans = await conn.fetch(
            "select * from floor_plans where property_id = $1 and is_current",
            property_id,
        )
        breakdown_objs = []
        compositions = []
        move_in_jsons: list[dict[str, Any]] = []
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
            facts = resolve_effective_facts(
                criterion_keys=rubric_keys,
                floor_plan_id=fp["id"],
                extractions=current_extractions,
                overrides=current_overrides,
                min_confidence=min_confidence,
                min_vision_confidence=min_vision_confidence,
                presence_like_keys=PRESENCE_LIKE_KEYS,
                boolean_presence_keys=BOOLEAN_PRESENCE_KEYS,
                generalized_unknown_keys=CONFIRMED_SCOPE_ONLY_KEYS,
            )
            values, gate_values = scoring_values_for_policy(facts, generalized_vision_policy)
            heating_value = resolve_effective_value(
                criterion_key="heating_type",
                floor_plan_id=fp["id"],
                extractions=current_extractions,
                min_confidence=min_confidence,
                presence_like=True,
                boolean_presence=False,
            )
            heating = (
                heating_value[0]
                if isinstance(heating_value, list)
                and len(heating_value) == 1
                and heating_value[0] in {"gas", "electric"}
                else None
            )
            rent = _conservative_rent(fp["rent_min"], fp["rent_max"])
            # §9.6: base rent is overrideable like any other cost component —
            # a leasing-office quote beats an advertised teaser. Floor-plan
            # scoped, append-only, revert by tombstone, exactly like the rest.
            rent_override = resolve_effective_value(
                criterion_key="base_rent",
                floor_plan_id=fp["id"],
                extractions=(),
                overrides=current_overrides,
                min_confidence=min_confidence,
            )
            if isinstance(rent_override, int | float):
                rent = float(rent_override)
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
                    utility_amounts=utility_amounts,
                    inclusions_unverified=included_ext is None,
                )
                if all_in_override is None and composition.total is not None:
                    values["all_in_monthly"] = composition.total
                    gate_values["all_in_monthly"] = composition.total
            # §9.5 P3-SC8. First month is base rent only — utilities and other
            # monthly fees stay in the all-in ledger, not this line. `rent`
            # already carries a `base_rent` override when one exists.
            move_in = compose_move_in(
                first_month_rent=rent,
                security_deposit=(
                    float(deposit_override)
                    if isinstance(
                        deposit_override := resolve_effective_value(
                            criterion_key="security_deposit",
                            floor_plan_id=fp["id"],
                            extractions=current_extractions,
                            overrides=current_overrides,
                            min_confidence=min_confidence,
                        ),
                        int | float,
                    )
                    else (float(fp["deposit"]) if fp["deposit"] is not None else None)
                ),
                charges=[replace(charge) for charge in one_time_charges],
            )
            move_in_override = resolve_effective_value(
                criterion_key="estimated_move_in_cost",
                floor_plan_id=fp["id"],
                extractions=(),
                overrides=current_overrides,
                min_confidence=min_confidence,
            )
            if move_in_override is None and move_in.total is not None:
                values["estimated_move_in_cost"] = move_in.total
                gate_values["estimated_move_in_cost"] = move_in.total
            breakdown_obj = score(
                rubric,
                values,
                floor_plan,
                rubric_version=rubric_version,
                gate_values=gate_values,
            )
            breakdown_objs.append(breakdown_obj)
            compositions.append(_composition_json(composition, all_in_override))
            move_in_json = move_in.to_json()
            if move_in_override is not None:
                try:
                    move_in_json["total"] = float(move_in_override)
                    move_in_json["overridden"] = True
                    move_in_json["incomplete"] = False
                except (TypeError, ValueError):
                    pass
            move_in_jsons.append(move_in_json)
            breakdown = breakdown_obj.to_contract()
            await conn.execute(
                """
                insert into scores
                    (hunt_listing_id, floor_plan_id, total, breakdown, rubric_version,
                     all_in_components, move_in_components)
                values ($1, $2, $3, $4::jsonb, $5, $6::jsonb, $7::jsonb)
                on conflict (hunt_listing_id, floor_plan_id) do update set
                    total = excluded.total,
                    breakdown = excluded.breakdown,
                    rubric_version = excluded.rubric_version,
                    all_in_components = excluded.all_in_components,
                    move_in_components = excluded.move_in_components,
                    computed_at = now()
                """,
                listing_id,
                fp["id"],
                Decimal(str(breakdown["total"])),
                json.dumps(breakdown),
                rubric_version,
                json.dumps(compositions[-1]) if compositions[-1] is not None else None,
                json.dumps(move_in_jsons[-1]),
            )
            upserted += 1
        if breakdown_objs:
            # Same display selection as SCORE: the display plan's composition
            # detail lands on hunt_listings.all_in_components (P3-9).
            display_index = select_display_score(breakdown_objs)
            display = compositions[display_index]
            await conn.execute(
                """
                update hunt_listings
                set all_in_components = $2::jsonb, move_in_components = $3::jsonb
                where id = $1
                """,
                listing_id,
                json.dumps(display) if display is not None else None,
                json.dumps(move_in_jsons[display_index]),
            )
    return upserted


async def rescore_listing(
    conn: asyncpg.Connection,
    *,
    hunt_listing_id: UUID,
    rubric: list[RubricCriterion],
    rubric_version: int,
    min_confidence: Confidence,
    min_vision_confidence: Confidence = Confidence.LOW,
    cats: int = 0,
    dogs: int = 0,
    cost_estimate_mode: str = "conservative",
    occupants: int = 1,
    generalized_vision_policy: str = "full_rubric",
) -> int:
    """Rescore one active Listing from canonical persisted facts and Overrides."""
    listing = await conn.fetchrow(
        """
        select hl.id, hl.property_id, hl.hunt_id, p.city, p.state, p.county
        from hunt_listings hl join properties p on p.id = hl.property_id
        where hl.id = $1 and hl.status = 'active'
        """,
        hunt_listing_id,
    )
    if listing is None:
        return 0
    return await _rescore_listings(
        conn,
        hunt_id=listing["hunt_id"],
        listings=[listing],
        rubric=rubric,
        rubric_version=rubric_version,
        min_confidence=min_confidence,
        min_vision_confidence=min_vision_confidence,
        cats=cats,
        dogs=dogs,
        cost_estimate_mode=cost_estimate_mode,
        occupants=occupants,
        generalized_vision_policy=generalized_vision_policy,
    )


async def rescore_hunt(
    conn: asyncpg.Connection,
    *,
    hunt_id: UUID,
    rubric: list[RubricCriterion],
    rubric_version: int,
    min_confidence: Confidence,
    min_vision_confidence: Confidence = Confidence.LOW,
    cats: int = 0,
    dogs: int = 0,
    cost_estimate_mode: str = "conservative",
    occupants: int = 1,
    generalized_vision_policy: str = "full_rubric",
) -> int:
    """Rescore every active Listing on the Hunt from persisted current facts."""
    listings = await conn.fetch(
        """
        select hl.id, hl.property_id, p.city, p.state, p.county from hunt_listings hl
        join properties p on p.id = hl.property_id
        where hl.hunt_id = $1 and hl.status = 'active'
        """,
        hunt_id,
    )
    upserted = await _rescore_listings(
        conn,
        hunt_id=hunt_id,
        listings=list(listings),
        rubric=rubric,
        rubric_version=rubric_version,
        min_confidence=min_confidence,
        min_vision_confidence=min_vision_confidence,
        cats=cats,
        dogs=dogs,
        cost_estimate_mode=cost_estimate_mode,
        occupants=occupants,
        generalized_vision_policy=generalized_vision_policy,
    )
    log.info("rescore_hunt_complete", hunt_id=str(hunt_id), score_rows=upserted)
    return upserted
