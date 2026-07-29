"""P3-SC8 (§9.5): the estimated move-in cost composer.

Goldens for the parts the design is explicit about — household multipliers,
credited deposits, refundability subtotals, unknown required inputs, and the
full-month fallback — plus the rule everything else hangs on: an incomplete
ledger yields a displayable subtotal and a *scoreless* total.
"""

from __future__ import annotations

from manzil_worker.stages.move_in import (
    Household,
    MoveInCharge,
    basis_multiplier,
    charge_from_extracted_fee,
    compose_move_in,
    default_required,
)

SOLO = Household(occupants=1, cats=0, dogs=0)
COUPLE_WITH_CAT = Household(occupants=2, cats=1, dogs=0)


def _charge(name: str, amount: float | None, **kwargs) -> MoveInCharge:
    return MoveInCharge(
        name=name, amount=amount, tag="actual" if amount is not None else "unknown", **kwargs
    )


def test_complete_ledger_totals_and_splits() -> None:
    result = compose_move_in(
        first_month_all_in=2146.0,
        security_deposit=500.0,
        charges=[
            _charge("application_fee", 150.0, refundable=False),
            _charge("admin", 225.0, refundable=False),
        ],
    )
    assert result.total == 3021.0
    assert result.subtotal == 3021.0
    assert result.incomplete is False
    # First month is non-refundable; the deposit is the refundable half.
    assert result.refundable_total == 500.0
    assert result.non_refundable_total == 2521.0
    assert result.unclassified_total == 0.0
    assert result.badges == []


def test_full_month_is_used_and_never_re_summed() -> None:
    """The first month enters as the composed all-in — one line, not rent plus
    fees again — and says why it is a whole month."""
    result = compose_move_in(
        first_month_all_in=1800.0, security_deposit=0.0, charges=[]
    )
    first = result.charges[0]
    assert first.name == "first_month"
    assert first.amount == 1800.0
    assert "full month" in (first.note or "")
    assert result.total == 1800.0


def test_unknown_required_component_withholds_the_total() -> None:
    result = compose_move_in(
        first_month_all_in=2146.0,
        security_deposit=500.0,
        charges=[_charge("pet_deposit", None, required=True, refundable=True)],
    )
    assert result.incomplete is True
    assert result.total is None, "an incomplete ledger must never score"
    assert result.subtotal == 2646.0, "what is known still displays"
    assert result.badges == ["move_in_incomplete"]


def test_unknown_optional_component_does_not_make_it_incomplete() -> None:
    result = compose_move_in(
        first_month_all_in=2146.0,
        security_deposit=500.0,
        charges=[_charge("pet_deposit", None, required=False, counted=False)],
    )
    assert result.incomplete is False
    assert result.total == 2646.0


def test_missing_all_in_or_deposit_is_incomplete() -> None:
    """The all-in's own strict-unknown branch propagates: no month, no total."""
    assert compose_move_in(
        first_month_all_in=None, security_deposit=500.0, charges=[]
    ).total is None
    assert compose_move_in(
        first_month_all_in=2000.0, security_deposit=None, charges=[]
    ).total is None


def test_credited_deposit_counts_only_its_non_credited_portion() -> None:
    result = compose_move_in(
        first_month_all_in=2000.0,
        security_deposit=500.0,
        charges=[
            _charge("holding_deposit", 300.0, refundable=True, credited=300.0),
            _charge("move_in_fee", 400.0, refundable=False, credited=250.0),
        ],
    )
    # 2000 + 500 + (300 - 300) + (400 - 250)
    assert result.total == 2650.0
    assert result.refundable_total == 500.0
    assert result.non_refundable_total == 2150.0


def test_credit_larger_than_the_charge_never_goes_negative() -> None:
    result = compose_move_in(
        first_month_all_in=1000.0,
        security_deposit=0.0,
        charges=[_charge("holding_deposit", 200.0, credited=500.0, refundable=True)],
    )
    assert result.total == 1000.0


def test_unknown_refundability_subtotals_separately() -> None:
    result = compose_move_in(
        first_month_all_in=1000.0,
        security_deposit=0.0,
        charges=[_charge("key_deposit", 150.0, refundable=None)],
    )
    assert result.unclassified_total == 150.0
    assert result.refundable_total == 0.0
    assert result.total == 1150.0


def test_uncounted_charge_is_visible_but_excluded() -> None:
    result = compose_move_in(
        first_month_all_in=1000.0,
        security_deposit=0.0,
        charges=[_charge("last_month_rent", 1795.0, required=False, counted=False)],
    )
    assert result.total == 1000.0
    assert [c.name for c in result.charges][-1] == "last_month_rent"
    assert result.charges[-1].amount == 1795.0


def test_basis_multipliers_follow_the_household() -> None:
    assert basis_multiplier("per_person", COUPLE_WITH_CAT) == 2
    assert basis_multiplier("per_pet", COUPLE_WITH_CAT) == 1
    assert basis_multiplier("per_pet", SOLO) == 0
    assert basis_multiplier("per_application", COUPLE_WITH_CAT) == 1
    assert basis_multiplier("flat", COUPLE_WITH_CAT) == 1
    assert basis_multiplier(None, COUPLE_WITH_CAT) == 1


def test_per_person_fee_multiplies_and_explains_itself() -> None:
    charge = charge_from_extracted_fee(
        {"name": "Application fee", "amount": 75.0, "basis": "per_person"},
        COUPLE_WITH_CAT,
        slot="application_fee",
    )
    assert charge.amount == 150.0
    assert charge.note == "$75.0 per person x 2"
    assert charge.counted is True


def test_pet_charges_drop_out_for_a_petless_household() -> None:
    charge = charge_from_extracted_fee(
        {"name": "Pet deposit", "amount": 300.0, "basis": "per_pet", "refundable": True},
        SOLO,
        slot="pet_deposit",
    )
    assert charge.required is False
    assert charge.counted is False
    assert charge.amount == 0.0
    assert default_required("pet_deposit", SOLO) is False
    assert default_required("pet_deposit", COUPLE_WITH_CAT) is True
    assert default_required("application_fee", SOLO) is True


def test_extracted_refundability_is_tri_state() -> None:
    silent = charge_from_extracted_fee({"name": "Admin fee", "amount": 200.0}, SOLO)
    assert silent.refundable is None, "silence is unknown, never non-refundable"
    stated = charge_from_extracted_fee(
        {"name": "Admin fee", "amount": 200.0, "refundable": False}, SOLO
    )
    assert stated.refundable is False


def test_extracted_charges_default_to_required() -> None:
    charge = charge_from_extracted_fee({"name": "Move-in fee", "amount": 400.0}, SOLO)
    assert charge.required is True
    assert charge.counted is True


def test_json_shape_is_stable() -> None:
    result = compose_move_in(
        first_month_all_in=1000.0,
        security_deposit=500.0,
        charges=[_charge("admin", 200.0, refundable=False, credited=50.0)],
    )
    payload = result.to_json()
    assert set(payload) == {
        "total",
        "subtotal",
        "refundable_total",
        "non_refundable_total",
        "unclassified_total",
        "incomplete",
        "charges",
        "badges",
    }
    admin = payload["charges"][-1]
    assert admin["credited"] == 50.0
    assert admin["required"] is True
    assert admin["counted"] is True
