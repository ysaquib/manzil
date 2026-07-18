"""P3-9: §9.5 full all-in composition goldens — heat rule, occupants scaling,
mode flip, the graduated unknown rule, and fee/estimate double-count guard.
Pure function, exact assertions (§15 golden discipline)."""

from __future__ import annotations

from manzil_worker.stages.pet_costs import beds_bucket, compose_all_in, slot_for_fee

BASELINES = {
    "electric": (120.0, 80.0),
    "electric_heat": (220.0, 140.0),
    "gas_heat": (150.0, 90.0),
    "water": (55.0, 40.0),
    "sewer": (45.0, 35.0),
    "trash": (30.0, 25.0),
}


def _compose(**overrides):  # type: ignore[no-untyped-def]
    kwargs = dict(
        rent=1800.0,
        pet_add=0.0,
        mandatory_fees=[],
        included=[],
        heating="gas",
        baselines=BASELINES,
        mode="conservative",
        occupants=1,
        beds=2,
    )
    kwargs.update(overrides)
    return compose_all_in(**kwargs)


def test_gas_heat_conservative_golden() -> None:
    comp = _compose()
    # electric 120 + gas_heat 150 + water 55 + sewer 45 + trash 30 = 400
    assert comp.total == 2200.0
    assert comp.estimated_total == 400.0
    assert comp.badges == []
    assert [c.tag for c in comp.components] == ["actual"] + ["estimated"] * 5


def test_electric_heat_uses_the_heating_inclusive_figure() -> None:
    comp = _compose(heating="electric")
    # electric_heat 220 + water 55 + sewer 45 + trash 30 = 350
    assert comp.total == 2150.0


def test_unknown_heating_takes_the_worse_variant_and_flags_it() -> None:
    comp = _compose(heating=None)
    assert comp.total == 2200.0  # gas variant (400) > electric variant (350)
    assert "heat_unknown" in comp.badges
    assert any("worse case" in (c.note or "") for c in comp.components)


def test_median_mode_relaxes_estimates_only() -> None:
    comp = _compose(mode="median")
    # 80 + 90 + 40 + 35 + 25 = 270; rent stays the conservative advertised figure
    assert comp.total == 2070.0
    assert comp.mode == "median"


def test_included_utilities_drop_their_components() -> None:
    comp = _compose(included=["water", "trash"])
    assert comp.total == 1800.0 + 120.0 + 150.0 + 45.0


def test_heat_included_drops_gas_and_downgrades_electric_heat_to_base() -> None:
    gas = _compose(included=["heat"])
    assert gas.total == 1800.0 + 120.0 + 55.0 + 45.0 + 30.0
    electric = _compose(included=["heat"], heating="electric")
    assert electric.total == gas.total  # electric_heat → base electric row


def test_occupants_scale_water_and_sewer_clamped() -> None:
    crowded = _compose(occupants=4, beds=2)  # factor 4/2 = 2.0
    assert crowded.total == 1800.0 + 120.0 + 150.0 + 110.0 + 90.0 + 30.0
    solo = _compose(occupants=1, beds=2)  # 0.5 clamps to 1.0 — never below baseline
    assert solo.total == 2200.0


def test_missing_baseline_row_withholds_the_total() -> None:
    partial = {k: v for k, v in BASELINES.items() if k != "trash"}
    comp = _compose(baselines=partial)
    assert comp.total is None
    assert "fees_unverified" in comp.badges
    (unknown,) = [c for c in comp.components if c.tag == "unknown"]
    assert unknown.name == "trash" and unknown.amount is None


def test_no_metro_baselines_falls_back_to_v1_slice() -> None:
    comp = _compose(baselines=None, pet_add=35.0, mandatory_fees=[("valet trash", 25.0)])
    assert comp.total == 1800.0 + 25.0 + 35.0
    assert "utilities_not_estimated" in comp.badges
    assert comp.estimated_total == 0.0


def test_page_silent_on_utilities_estimates_conservatively_with_badge() -> None:
    comp = _compose(included=None)
    assert comp.total == 2200.0
    assert "fees_unverified" in comp.badges


def test_billed_fee_suppresses_the_matching_estimate() -> None:
    comp = _compose(mandatory_fees=[("water/sewer billing", 60.0), ("valet trash", 25.0)])
    # water+sewer+trash estimates dropped; fees counted once as actuals
    assert comp.total == 1800.0 + 60.0 + 25.0 + 120.0 + 150.0


def test_slot_mapping_and_bucket() -> None:
    assert slot_for_fee("Valet Trash") == "valet_trash"
    assert slot_for_fee("water/sewer billing") == "water_sewer"
    assert slot_for_fee("Required renters insurance program") == "insurance_program"
    assert slot_for_fee("Amenity fee") is None
    assert [beds_bucket(b) for b in (0, 1, 2, 3, 5)] == [0, 1, 2, 3, 3]
