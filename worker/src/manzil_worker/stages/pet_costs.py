"""Species-specific pet-rent composition (§9.5 v1).

Worker-local by design: the shared scoring engine stays domain-blind and pure,
so the rental-specific arithmetic that folds pet rent into `all_in_monthly`
lives here and is shared by SCORE (ingest path) and rescore so the two never
drift. Facts in, a monthly dollar figure out — nothing else.
"""

from __future__ import annotations


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
