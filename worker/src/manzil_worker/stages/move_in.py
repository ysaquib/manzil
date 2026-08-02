"""§9.5 P3-SC8 estimated move-in cost: required cash from application through
occupancy for one Floor Plan.

Worker-local for the same reason the all-in composer is (`pet_costs`): the
shared engine stays domain-blind, so this rental arithmetic lives here and is
shared by SCORE (ingest) and rescore so the two never drift.

Contract (DESIGN §9.5):

    first_month_rent + security_deposit + application/admin fees
    + one-time pet deposits/fees + other required one-time charges
    + explicitly required prepaid/last-month rent
    + the non-credited portion of holding deposits

`first_month_rent` is base rent only — utilities and other monthly fees belong
in the all-in ledger, not the first-month move-in line. One full month is used
because no Source states a prorated schedule. Optional
charges never count. Refundable amounts still require cash, so they are
included in the figure but subtotal separately.

Incomplete semantics: a materially unknown *required* component yields a known
subtotal plus `incomplete`, and `total` stays None so the
`estimated_move_in_cost` Criterion scores unknown. The subtotal is never
presented or scored as a conservative lower bound — a partial number that looks
like a total is exactly the lie this tool exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Tag = Literal["actual", "estimated", "unknown"]

# One-time slots are required to move in unless a human says otherwise. Pet
# slots are the exception: required only when the hunt's household has pets —
# the same rule that keeps pet rent out of a petless household's all-in.
_PET_SLOTS = frozenset({"pet_deposit", "pet_fee"})


@dataclass
class MoveInCharge:
    """One line of the move-in ledger.

    `amount` is the full charge for this household (basis multipliers already
    applied); `credited` is the part applied to first month's rent, so the cash
    this line actually requires is `amount - credited`. `refundable` is
    tri-state: None means no Source said, and it is never read as False.
    """

    name: str
    amount: float | None
    tag: Tag
    required: bool = True
    refundable: bool | None = None
    credited: float = 0.0
    counted: bool = True
    note: str | None = None

    @property
    def cash(self) -> float | None:
        """Cash this line requires at move-in, after any credit."""
        if self.amount is None or not self.counted:
            return None if self.amount is None else 0.0
        return round(max(self.amount - self.credited, 0.0), 2)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "amount": self.amount,
            "tag": self.tag,
            "required": self.required,
            "refundable": self.refundable,
            "counted": self.counted,
        }
        if self.credited:
            out["credited"] = round(self.credited, 2)
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class MoveInComposition:
    """`total` None ⇒ the Criterion scores unknown. `subtotal` is what is known
    and is always safe to display beside the `incomplete` flag."""

    total: float | None
    subtotal: float
    refundable_total: float
    non_refundable_total: float
    unclassified_total: float
    incomplete: bool
    charges: list[MoveInCharge] = field(default_factory=list)
    badges: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "subtotal": self.subtotal,
            "refundable_total": self.refundable_total,
            "non_refundable_total": self.non_refundable_total,
            "unclassified_total": self.unclassified_total,
            "incomplete": self.incomplete,
            "charges": [charge.to_json() for charge in self.charges],
            "badges": self.badges,
        }


@dataclass
class Household:
    occupants: int = 1
    cats: int = 0
    dogs: int = 0

    @property
    def pets(self) -> int:
        return self.cats + self.dogs


def basis_multiplier(basis: str | None, household: Household) -> int:
    """How many times one stated charge is paid by this household (§9.5).

    `per_application` and `flat` are paid once; `per_person` scales with
    occupants; `per_pet` with the household's pets — which is zero for a
    petless household, and that is the whole point: a pet deposit is not this
    household's cost.
    """
    if basis == "per_person":
        return max(household.occupants, 1)
    if basis == "per_pet":
        return household.pets
    return 1


def _classify(charges: list[MoveInCharge]) -> tuple[float, float, float]:
    refundable = non_refundable = unclassified = 0.0
    for charge in charges:
        cash = charge.cash
        if cash is None or not charge.counted:
            continue
        if charge.refundable is True:
            refundable += cash
        elif charge.refundable is False:
            non_refundable += cash
        else:
            unclassified += cash
    return round(refundable, 2), round(non_refundable, 2), round(unclassified, 2)


def compose_move_in(
    *,
    first_month_rent: float | None,
    security_deposit: float | None,
    charges: list[MoveInCharge],
    first_month_note: str | None = None,
) -> MoveInComposition:
    """The full §9.5 P3-SC8 composition for one Floor Plan.

    `first_month_rent` None means base rent is unknown — the move-in figure
    inherits that unknown rather than quietly dropping a month of rent from the
    cash requirement.
    """
    ledger: list[MoveInCharge] = [
        MoveInCharge(
            name="first_month",
            amount=first_month_rent,
            tag="actual" if first_month_rent is not None else "unknown",
            required=True,
            refundable=False,
            note=first_month_note or "base rent — one full month, no prorated schedule stated",
        ),
        MoveInCharge(
            name="security_deposit",
            amount=(float(security_deposit) if security_deposit is not None else None),
            tag="actual" if security_deposit is not None else "unknown",
            required=True,
            refundable=True,
        ),
        *charges,
    ]

    subtotal = round(
        sum(
            charge.cash or 0.0
            for charge in ledger
            if charge.counted and charge.amount is not None
        ),
        2,
    )
    incomplete = any(
        charge.required and charge.counted and charge.amount is None for charge in ledger
    )
    refundable_total, non_refundable_total, unclassified_total = _classify(ledger)
    badges = ["move_in_incomplete"] if incomplete else []
    return MoveInComposition(
        total=None if incomplete else subtotal,
        subtotal=subtotal,
        refundable_total=refundable_total,
        non_refundable_total=non_refundable_total,
        unclassified_total=unclassified_total,
        incomplete=incomplete,
        charges=ledger,
        badges=badges,
    )


def charge_from_extracted_fee(
    fee: dict[str, Any],
    household: Household,
    *,
    slot: str | None = None,
) -> MoveInCharge:
    """A `one_time_fees` extraction entry as a ledger line.

    Extracted move-in charges default to required — the conservative reading,
    since a page that lists a move-in charge without calling it optional is
    far more often stating a condition than an offer. A human unticks the ones
    that are genuinely optional, and that decision persists on the slot.
    """
    name = str(fee.get("name") or slot or "one-time fee")
    basis = fee.get("basis")
    raw = fee.get("amount")
    multiplier = basis_multiplier(basis if isinstance(basis, str) else None, household)
    amount = round(float(raw) * multiplier, 2) if isinstance(raw, int | float) else None
    refundable = fee.get("refundable")
    required = True
    if slot in _PET_SLOTS or basis == "per_pet":
        required = household.pets > 0
    note = None
    if multiplier != 1:
        unit = "person" if basis == "per_person" else "pet"
        note = f"${raw} per {unit} x {multiplier}"
    return MoveInCharge(
        name=slot or name,
        amount=amount,
        tag="actual" if amount is not None else "unknown",
        required=required,
        refundable=refundable if isinstance(refundable, bool) else None,
        # An optional charge is shown but not counted; the UI dims and strikes
        # it rather than hiding what the page said.
        counted=required,
        note=note,
    )


def default_required(slot: str, household: Household) -> bool:
    """Whether a one-time checklist slot is required to move in, absent a human
    decision. Pet charges are required only for a household with pets; every
    other standard move-in slot (application, admin, and the rest) is required
    until someone says otherwise."""
    if slot in _PET_SLOTS:
        return household.pets > 0
    return True
