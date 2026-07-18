"""§9.5 all-in composition (v1 pet rent 2026-07-10; full composer P3-9).

Worker-local by design: the shared scoring engine stays domain-blind and pure,
so the rental-specific arithmetic that composes `all_in_monthly` lives here and
is shared by SCORE (ingest path) and rescore so the two never drift. Facts in,
a tagged component list and a monthly dollar figure out — nothing else.

Composition (§9.5): `all_in = rent + mandatory_fees + pet_monthly +
Σ(estimated non-included utilities)`, every component tagged
`actual | estimated | unknown`. Conservative by default (`monthly_high`, the
winter-weighted peak month); `cost_estimate_mode = median` relaxes the
estimated components only — rent stays the advertised conservative figure in
both modes (never look cheaper than reality).

Graduated unknown rule (§20 2026-07-18):
- Metro has NO baselines yet (or no metro identity): compose the v1 slice
  (rent + fees + pet), badge `utilities_not_estimated`. Behavior-identical to
  the shipped v1 until the scheduler's baselines job learns the metro.
- Metro HAS baselines but a needed utility row is missing: the machinery is
  live and a bill we know exists cannot be priced — the total is withheld
  (criterion scores `unknown_delta`), the component tags `unknown`, badge
  `fees_unverified`. Never a fabricated number.

Heat rule (§9.5): gas heat → base `electric` + `gas_heat`; electric heat →
`electric_heat` (heating-inclusive); unknown heating → the WORSE of the two
variants, badge `heat_unknown`. `utilities_included` drops covered components
("heat" included drops the heating figure; electric-heat units then still owe
base `electric`).

Occupants scaling (§20 2026-07-18, the reserved reader): water and sewer are
per-person — scale by `clamp(occupants / max(1, beds), 1.0, 2.0)`; the factor
never drops below 1 so scaling only ever raises the estimate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CONSERVATIVE = "conservative"

# Utilities the composition estimates when not included (§9.5). Internet/cable
# stay inclusion-flags only — every household pays them regardless of listing,
# so they add nothing to comparability (§20 2026-07-18).
_PER_PERSON_UTILITIES = frozenset({"water", "sewer"})

# fee_checklist slots the extracted mandatory fees may fill (pet slots are
# §9.5 v1's; admin is one-time and never composes).
MANDATORY_FEE_SLOTS = ("water_sewer", "valet_trash", "parking", "insurance_program")
_MANDATORY_SLOT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("water_sewer", ("water", "sewer", "utility billing", "utilities billing")),
    ("valet_trash", ("trash", "waste")),
    ("parking", ("parking", "garage", "carport")),
    ("insurance_program", ("insurance", "liability")),
)


# Fee slots that stand in for a utility's cost: composing both the billed fee
# and the baseline estimate would double-count.
_SLOT_COVERS: dict[str, tuple[str, ...]] = {
    "water_sewer": ("water", "sewer"),
    "valet_trash": ("trash",),
}


def slot_for_fee(name: str) -> str | None:
    """The fee_checklist slot an extracted mandatory fee lands in, by keyword —
    None when no standard slot matches (the fee still composes via the
    `mandatory_fees` extraction row; it just has no checklist affordance)."""
    lowered = name.lower()
    for slot, keywords in _MANDATORY_SLOT_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return slot
    return None


def beds_bucket(beds: int) -> int:
    """utility_baselines bucket: 0..3, where 3 means 3+ bedrooms."""
    return min(max(beds, 0), 3)


Tag = Literal["actual", "estimated", "unknown"]


@dataclass
class Component:
    """One §9.5 composition line. `amount` is None only when tag == unknown."""

    name: str
    amount: float | None
    tag: Tag
    note: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "amount": self.amount, "tag": self.tag}
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class AllInComposition:
    """`total` None ⇒ the criterion scores unknown (`unknown_delta`) — the
    strict branch of the graduated rule. `badges`: `fees_unverified`,
    `heat_unknown`, `utilities_not_estimated`."""

    total: float | None
    components: list[Component] = field(default_factory=list)
    badges: list[str] = field(default_factory=list)
    mode: str = CONSERVATIVE

    @property
    def estimated_total(self) -> float:
        return round(
            sum(c.amount for c in self.components if c.tag == "estimated" and c.amount), 2
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "estimated_total": self.estimated_total,
            "components": [c.to_json() for c in self.components],
            "badges": self.badges,
            "mode": self.mode,
        }


def _occupancy_factor(occupants: int, beds: int) -> float:
    return min(max(occupants / max(1, beds), 1.0), 2.0)


def _utility_components(
    heating_variant: str,
    included: set[str],
    baselines: dict[str, tuple[float, float]],
    *,
    mode: str,
    occupants: int,
    beds: int,
) -> list[Component]:
    """The estimated/unknown utility components for one heating variant
    ('gas' | 'electric'). A needed utility missing from `baselines` yields an
    unknown component (strict branch)."""
    if heating_variant == "gas":
        needed = [("electric", "electric"), ("gas", "gas_heat")]
    else:
        # Electric heat: one heating-inclusive electric figure — unless "heat"
        # is included, which covers heating but leaves base electric owed.
        needed = [("electric", "electric" if "heat" in included else "electric_heat")]
    needed += [("water", "water"), ("sewer", "sewer"), ("trash", "trash")]

    out: list[Component] = []
    for kind, baseline_key in needed:
        if kind in included or (kind == "gas" and "heat" in included):
            continue
        row = baselines.get(baseline_key)
        if row is None:
            out.append(
                Component(name=kind, amount=None, tag="unknown", note="no baseline figure")
            )
            continue
        amount = row[0] if mode == CONSERVATIVE else row[1]
        note = "winter-weighted" if baseline_key in ("electric_heat", "gas_heat") else None
        if kind in _PER_PERSON_UTILITIES:
            amount *= _occupancy_factor(occupants, beds)
        out.append(Component(name=kind, amount=round(amount, 2), tag="estimated", note=note))
    return out


def compose_all_in(
    *,
    rent: float,
    pet_add: float,
    mandatory_fees: list[tuple[str, float]],
    included: list[str] | None,
    heating: str | None,
    baselines: dict[str, tuple[float, float]] | None,
    mode: str = CONSERVATIVE,
    occupants: int = 1,
    beds: int = 1,
) -> AllInComposition:
    """The full §9.5 composition for one floor plan. `baselines` maps utility →
    (monthly_high, monthly_median) for this plan's beds bucket; None means the
    metro has no baseline data at all (graceful v1 fallback)."""
    components: list[Component] = [Component(name="rent", amount=rent, tag="actual")]
    badges: list[str] = []

    for name, amount in mandatory_fees:
        components.append(Component(name=name, amount=round(amount, 2), tag="actual"))
    if pet_add:
        components.append(Component(name="pet rent", amount=round(pet_add, 2), tag="actual"))

    if included is None:
        # Page silent on utilities: assume none included (conservative — the
        # estimate only ever raises the number) and say so.
        badges.append("fees_unverified")
        included_set: set[str] = set()
    else:
        included_set = set(included)
    # An actual billed fee beats a baseline estimate: a water/sewer billing fee
    # or valet-trash fee IS that utility's cost — estimating it again would
    # double-count (§20 2026-07-18).
    for name, _ in mandatory_fees:
        for kind in _SLOT_COVERS.get(slot_for_fee(name) or "", ()):
            included_set.add(kind)

    if baselines is None:
        badges.append("utilities_not_estimated")
        utility_components: list[Component] = []
    elif heating in ("gas", "electric"):
        utility_components = _utility_components(
            heating, included_set, baselines, mode=mode, occupants=occupants, beds=beds
        )
    else:
        # Unknown heating: the worse of the two variants (§9.5). A variant with
        # an unknown component can't be compared — strictness wins.
        variants = [
            _utility_components(
                v, included_set, baselines, mode=mode, occupants=occupants, beds=beds
            )
            for v in ("gas", "electric")
        ]
        computable = [v for v in variants if all(c.amount is not None for c in v)]
        variant_decided = False
        if len(computable) == len(variants):
            utility_components = max(
                variants, key=lambda v: sum(c.amount or 0.0 for c in v)
            )
            variant_decided = True
        elif not computable:
            utility_components = variants[0]  # both carry unknowns; either reports them
        else:
            # One variant priceable, the other not: "worse" is undecidable.
            utility_components = [
                c if c.amount is None else Component(c.name, None, "unknown", c.note)
                for c in variants[0]
            ]
        badges.append("heat_unknown")
        if variant_decided:
            # Note only the lines the variant choice changed — water/sewer/trash
            # price identically either way, so a note there is noise.
            chosen = (
                "gas heat" if any(c.name == "gas" for c in utility_components) else "electric heat"
            )
            for c in utility_components:
                if c.tag == "estimated" and c.name in ("electric", "gas"):
                    c.note = (c.note + "; " if c.note else "") + (
                        f"heating type unknown — priced as {chosen} (the costlier setup)"
                    )

    components.extend(utility_components)

    if any(c.tag == "unknown" for c in components):
        if "fees_unverified" not in badges:
            badges.append("fees_unverified")
        total = None
    else:
        total = round(sum(c.amount or 0.0 for c in components), 2)
    return AllInComposition(total=total, components=components, badges=badges, mode=mode)


def pet_monthly(
    *,
    cats: int,
    dogs: int,
    cat_rent: float | None,
    dog_rent: float | None,
    generic_rent: float | None,
) -> float:
    """Total monthly pet rent = cats·(cat_rent ?? generic) + dogs·(dog_rent ??
    generic). A species with no species-specific AND no generic rent contributes
    0 — the slot stays visibly unfilled rather than being fabricated."""
    cat_effective = cat_rent if cat_rent is not None else generic_rent
    dog_effective = dog_rent if dog_rent is not None else generic_rent
    total = 0.0
    if cat_effective is not None:
        total += cats * cat_effective
    if dog_effective is not None:
        total += dogs * dog_effective
    return total
