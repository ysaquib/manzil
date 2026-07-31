"""The built-in Visit Checklist template — canonical source (DESIGN §9.7, VC-1).

This module is the source of truth for `visit_template_items`. The table is
seeded by generated SQL embedded in a migration; `generate_template_sql()`
produces it and a parity test asserts the committed migration still matches, so
the two can never drift silently. Same arrangement `criteria_catalog` uses with
`supabase/seed.sql`.

**Why here and not in `shared/`:** `shared/` stays domain-blind (repo AGENTS.md).
A rental tour checklist is irreducibly rental-specific, so it lives with the API.

**Versioning.** `TEMPLATE_VERSION` is frozen into every Visit at creation
(`visits.template_version`), so editing this module never rewrites what a
finished Visit asked or what its completion percentage meant. A new version gets
a new migration seeding the new rows; old rows stay for old Visits.

**Content** transcribes `docs/apartment-tour-checklist.md`. Where that document
lists the same check twice (the ten-minute sweep repeats items that also appear
in a room section) only one item exists here — a checklist that asks the same
question twice gets filled in inconsistently.

**Section titles deliberately do not live in the database.** DESIGN §8.2 gives
items a `section_key` and a `display_order` and no section table; `display_order`
is globally monotonic here, so section grouping *and* section order both derive
from the items. Human-readable section titles are frontend copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

TEMPLATE_VERSION = 1

Tier = Literal["quick", "standard", "thorough"]
Kind = Literal["fact", "check", "question", "impression"]
Scope = Literal["property", "unit"]

# ---------------------------------------------------------------------------
# Item model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateItem:
    key: str
    section_key: str
    tier: Tier
    kind: Kind
    scope: Scope
    label: str
    help: str | None = None
    value_schema: dict[str, Any] = field(default_factory=dict)
    is_critical: bool = False


# Value schemas. `check` needs none — its tri-state is implied by the kind.
TEXT: dict[str, Any] = {"type": "text"}
INT: dict[str, Any] = {"type": "integer"}
MONEY: dict[str, Any] = {"type": "money"}
RATING: dict[str, Any] = {"type": "rating", "max": 5}
FLAG: dict[str, Any] = {"type": "boolean"}


def _int(unit: str) -> dict[str, Any]:
    return {"type": "integer", "unit": unit}


def _num(unit: str) -> dict[str, Any]:
    return {"type": "number", "unit": unit}


def _enum(*options: str) -> dict[str, Any]:
    return {"type": "enum", "options": list(options)}


def _multi(*options: str) -> dict[str, Any]:
    return {"type": "multiselect", "options": list(options)}


_HEARD = _multi(
    "traffic",
    "neighbours",
    "hallway",
    "hvac",
    "plumbing",
    "trains_or_planes",
    "bar_or_restaurant",
    "construction",
    "nothing",
)

# ---------------------------------------------------------------------------
# The template. Order here is display order.
# ---------------------------------------------------------------------------


def _ck(key: str, section: str, scope: Scope, label: str, tier: Tier = "standard", **kw: Any):
    return TemplateItem(key, section, tier, "check", scope, label, **kw)


def _ft(
    key: str,
    section: str,
    scope: Scope,
    label: str,
    schema: dict[str, Any],
    tier: Tier = "standard",
    **kw: Any,
):
    return TemplateItem(key, section, tier, "fact", scope, label, value_schema=schema, **kw)


def _qn(key: str, section: str, scope: Scope, label: str, tier: Tier = "standard", **kw: Any):
    return TemplateItem(key, section, tier, "question", scope, label, value_schema=TEXT, **kw)


def _im(
    key: str,
    section: str,
    scope: Scope,
    label: str,
    schema: dict[str, Any],
    tier: Tier = "standard",
    **kw: Any,
):
    return TemplateItem(key, section, tier, "impression", scope, label, value_schema=schema, **kw)


def _notes(section: str, scope: Scope = "unit"):
    """Notes are personal: two people walking one apartment notice different things."""
    return _im(f"{section}_notes", section, scope, "Notes", TEXT)


TEMPLATE: tuple[TemplateItem, ...] = (
    # -- 1. Essentials: must-haves, pass or fail ----------------------------
    _ck("ess_budget", "essentials", "unit", "Total monthly cost is within budget", "quick"),
    _ck("ess_bedrooms", "essentials", "unit", "Bedroom count and size work", "quick"),
    _ck(
        "ess_laundry",
        "essentials",
        "unit",
        "In-unit laundry, or an acceptable alternative",
        "quick",
    ),
    _ck("ess_pets", "essentials", "property", "Pet policy works", "quick"),
    _ck("ess_parking", "essentials", "property", "Parking works", "quick"),
    _ck("ess_safe", "essentials", "property", "Feels safe", "quick"),
    _ck("ess_commute", "essentials", "property", "Commute is acceptable", "quick"),
    _ck("ess_available", "essentials", "unit", "Available when you need it", "quick"),
    # -- 2. The ten-minute sweep -------------------------------------------
    _ck(
        "sweep_pressure",
        "sweep",
        "unit",
        "Run the kitchen tap and the shower at the same time",
        "quick",
        help="Does the pressure hold?",
    ),
    _ft("sweep_hot_water_secs", "sweep", "unit", "Hot water arrives in", _int("sec"), "quick"),
    _ck("sweep_hot_water_stays", "sweep", "unit", "Hot water stays hot", "quick"),
    _ck("sweep_toilets", "sweep", "unit", "Flush every toilet", "quick"),
    _ck(
        "sweep_heat_ac",
        "sweep",
        "unit",
        "Turn on the heat, then the A/C",
        "quick",
        help="Do both respond?",
    ),
    _ck(
        "sweep_under_sinks",
        "sweep",
        "unit",
        "Look under every sink",
        "quick",
        help="Leaks, stains, warped wood",
    ),
    _ck("sweep_windows", "sweep", "unit", "Open, close and lock every window"),
    _ck(
        "sweep_outlets",
        "sweep",
        "unit",
        "Test an outlet in each room",
        help="A phone charger is enough",
    ),
    _ft(
        "sweep_smells",
        "sweep",
        "unit",
        "Smell test",
        _multi("mildew", "smoke", "pets", "sewage", "air_freshener_masking", "nothing_unusual"),
        "quick",
    ),
    _ft(
        "sweep_heard",
        "sweep",
        "unit",
        "Stand still and listen for 60 seconds",
        _HEARD,
        "quick",
    ),
    _ft("sweep_cell_bars", "sweep", "unit", "Cell signal in the worst room", _int("bars"), "quick"),
    _ft(
        "sweep_actual_unit",
        "sweep",
        "unit",
        "Is this the actual unit you'd rent, or a model?",
        _enum("actual", "model"),
        "quick",
        is_critical=True,
    ),
    # -- 3. Before the tour -------------------------------------------------
    _ck("prep_reviews", "prep", "property", "Read the online reviews"),
    _ft("prep_review_pattern", "prep", "property", "Pattern of complaints", TEXT),
    _ck("prep_crime", "prep", "property", "Checked area crime and safety data"),
    _ck("prep_flood", "prep", "property", "Checked flood risk"),
    _ft(
        "prep_commute_min",
        "prep",
        "property",
        "Commute at your real departure hour",
        _int("min"),
        "quick",
    ),
    _ck(
        "prep_errands",
        "prep",
        "property",
        "Looked up grocery, pharmacy, gym and place-of-worship distances",
    ),
    _ck(
        "prep_internet",
        "prep",
        "property",
        "Checked which internet providers serve the address, and max speed",
    ),
    _ft(
        "prep_building_age",
        "prep",
        "property",
        "Building age",
        INT,
        help="Pre-1978 means a lead-paint disclosure is required by law",
    ),
    _ck(
        "prep_construction",
        "prep",
        "property",
        "Searched for planned construction or demolition nearby",
        "thorough",
    ),
    _ck("prep_nonnegotiables", "prep", "property", "Wrote down your non-negotiables", "thorough"),
    _ck(
        "prep_still_available",
        "prep",
        "property",
        "Confirmed the units are still available",
        "quick",
    ),
    # -- 4. Kitchen ---------------------------------------------------------
    _im("kitchen_fridge", "kitchen", "unit", "Fridge", RATING),
    _im("kitchen_stove", "kitchen", "unit", "Stove", RATING),
    _im("kitchen_oven", "kitchen", "unit", "Oven", RATING),
    _im("kitchen_dishwasher", "kitchen", "unit", "Dishwasher", RATING),
    _im("kitchen_microwave", "kitchen", "unit", "Microwave", RATING, "thorough"),
    _ft(
        "kitchen_stove_type", "kitchen", "unit", "Stove type", _enum("gas", "electric", "induction")
    ),
    _ck("kitchen_opened", "kitchen", "unit", "Opened the fridge, oven and dishwasher"),
    _ck("kitchen_disposal", "kitchen", "unit", "Ran the disposal"),
    _ck(
        "kitchen_hood_vents_outside",
        "kitchen",
        "unit",
        "Exhaust hood vents outside",
        help="Not recirculating — matters a lot for heavy cooking",
    ),
    _ck(
        "kitchen_counter_space",
        "kitchen",
        "unit",
        "Counter space works for how you actually cook",
        "thorough",
    ),
    _ck(
        "kitchen_cabinets_open",
        "kitchen",
        "unit",
        "Cabinets and drawers open fully, no collisions",
        "thorough",
    ),
    _ck(
        "kitchen_cabinet_interiors",
        "kitchen",
        "unit",
        "Looked inside the cabinets",
        help="Droppings, water stains, smell",
    ),
    _ft("kitchen_counter_outlets", "kitchen", "unit", "Counter outlets", INT, "thorough"),
    _ft("kitchen_storage", "kitchen", "unit", "Storage", _enum("generous", "adequate", "tight")),
    _notes("kitchen"),
    # -- 5. Bathrooms -------------------------------------------------------
    _ft("bath_count", "bathrooms", "unit", "Bathrooms", INT, "quick"),
    _ck("bath_pressure", "bathrooms", "unit", "Shower pressure is strong", "quick"),
    _ck("bath_drains", "bathrooms", "unit", "Drains fast", help="Run it a full minute"),
    _ck("bath_toilet", "bathrooms", "unit", "Toilet flushes and refills normally"),
    _ck(
        "bath_fan",
        "bathrooms",
        "unit",
        "Exhaust fan works and is vented",
        help="Run it — is it deafening?",
    ),
    _ck(
        "bath_mildew", "bathrooms", "unit", "No mildew in grout, caulk or ceiling corners", "quick"
    ),
    _ck(
        "bath_soft_spots",
        "bathrooms",
        "unit",
        "No soft spots or discolouration around the toilet or tub base",
    ),
    _ck("bath_storage", "bathrooms", "unit", "Storage is adequate", "thorough"),
    _ck("bath_door_locks", "bathrooms", "unit", "Door closes and locks", "thorough"),
    _ft("bath_type", "bathrooms", "unit", "Bathing", _enum("tub", "standing_shower", "both")),
    _im("bath_condition", "bathrooms", "unit", "Condition", RATING),
    _notes("bathrooms"),
    # -- 6. Bedrooms and closets -------------------------------------------
    _ft("bed_count", "bedrooms", "unit", "Bedrooms", INT, "quick"),
    _ck(
        "bed_window_each",
        "bedrooms",
        "unit",
        "Every bedroom has a window",
        "quick",
        help="Fire-code requirement",
    ),
    _ck("bed_fits", "bedrooms", "unit", "Your bed fits with walking room", help="Measure it"),
    _ft("bed_closet_width", "bedrooms", "unit", "Closet width", _num("in")),
    _ft(
        "bed_closet_type",
        "bedrooms",
        "unit",
        "Closet type",
        _enum("reach_in", "walk_in", "wardrobe_only", "none"),
    ),
    _ck("bed_doors_latch", "bedrooms", "unit", "Doors close and latch properly", "thorough"),
    _ck(
        "bed_outlets", "bedrooms", "unit", "Outlets usefully placed relative to the bed", "thorough"
    ),
    _ck("bed_overhead_light", "bedrooms", "unit", "Overhead light or ceiling fan present"),
    _ft(
        "bed_window_direction",
        "bedrooms",
        "unit",
        "Window direction",
        _enum("n", "ne", "e", "se", "s", "sw", "w", "nw"),
        "thorough",
    ),
    _im("bed_light_quality", "bedrooms", "unit", "Light quality", RATING),
    _notes("bedrooms"),
    # -- 7. Living areas, light and windows --------------------------------
    _ft(
        "living_light_level",
        "living",
        "unit",
        "Natural light",
        _enum("bright", "moderate", "dark"),
        "quick",
    ),
    _ck("living_windows_operate", "living", "unit", "Windows open, close and lock"),
    _ck("living_screens", "living", "unit", "Screens present and intact", "thorough"),
    _ck("living_insulated", "living", "unit", "Double-pane, or feels insulated"),
    _ck("living_drafts", "living", "unit", "No drafts at the frames or doors"),
    _ck(
        "living_blinds",
        "living",
        "unit",
        "Blinds or curtains included and in good condition",
        "thorough",
    ),
    _ck(
        "living_walls",
        "living",
        "unit",
        "Walls and ceilings free of cracks, stains and patch marks",
    ),
    _ck(
        "living_floors_level",
        "living",
        "unit",
        "Floors are level",
        help="No bounce, slope or squeak",
    ),
    _ft(
        "living_flooring_type",
        "living",
        "unit",
        "Flooring",
        _enum(
            "carpet",
            "hardwood",
            "engineered_wood",
            "laminate",
            "vinyl",
            "tile",
            "concrete",
            "other",
        ),
    ),
    _im("living_flooring_condition", "living", "unit", "Flooring condition", RATING),
    _ft("living_view", "living", "unit", "The actual view", TEXT),
    _ft("living_balcony", "living", "unit", "Balcony or patio", _enum("yes", "no")),
    _ft("living_balcony_detail", "living", "unit", "Balcony size and condition", TEXT, "thorough"),
    _notes("living"),
    # -- 8. Laundry ---------------------------------------------------------
    _ft(
        "laundry_type",
        "laundry",
        "unit",
        "Laundry",
        _enum("in_unit", "shared_in_building", "off_site", "hookups_only"),
        "quick",
    ),
    _ft(
        "laundry_config",
        "laundry",
        "unit",
        "Configuration",
        _enum("full_size", "stacked", "combo"),
        "thorough",
    ),
    _ft("laundry_venting", "laundry", "unit", "Venting", _enum("vented", "ventless"), "thorough"),
    _ck("laundry_powered_on", "laundry", "unit", "Powered them on"),
    _ft("laundry_shared_machines", "laundry", "property", "Shared machines", INT, "thorough"),
    _ft("laundry_shared_cost", "laundry", "property", "Cost per load", MONEY, "thorough"),
    _ft(
        "laundry_shared_payment",
        "laundry",
        "property",
        "Payment",
        _enum("card", "coin", "app"),
        "thorough",
    ),
    _ft("laundry_shared_hours", "laundry", "property", "Hours", TEXT, "thorough"),
    _notes("laundry"),
    # -- 9. HVAC, plumbing and electrical ----------------------------------
    _ft(
        "sys_heat_type",
        "systems",
        "unit",
        "Heating",
        _enum("forced_air", "radiator", "baseboard", "heat_pump", "other"),
    ),
    _ft(
        "sys_cooling_type",
        "systems",
        "unit",
        "Cooling",
        _enum("central", "window", "mini_split", "none"),
    ),
    _ck("sys_thermostat", "systems", "unit", "Thermostat is in-unit and you control it"),
    _ck("sys_vents", "systems", "unit", "Vents in every room, unobstructed"),
    _ck(
        "sys_insulation",
        "systems",
        "unit",
        "Insulation feels adequate",
        "thorough",
        help="Cold walls? Drafty corners?",
    ),
    _ck("sys_rust_water", "systems", "unit", "No rust-coloured water after 30 seconds"),
    _ft("sys_water_heater", "systems", "unit", "Water heater", _enum("in_unit", "shared")),
    _ft(
        "sys_water_heater_size",
        "systems",
        "unit",
        "Water heater size or capacity",
        TEXT,
        "thorough",
    ),
    _ck(
        "sys_sump_pump",
        "systems",
        "unit",
        "Sump pump present and appears functional, if applicable",
        "thorough",
    ),
    _ck("sys_gfci", "systems", "unit", "GFCI outlets in the kitchen and bathrooms"),
    _ft(
        "sys_panel",
        "systems",
        "unit",
        "Panel",
        _enum("breakers", "fuses"),
        help="Fuses mean old wiring",
    ),
    _ck("sys_switches", "systems", "unit", "All switches work, no flicker", "thorough"),
    _ck(
        "sys_desk_outlets",
        "systems",
        "unit",
        "Enough outlets for a desk or office setup",
        "thorough",
    ),
    _notes("systems"),
    # -- 10. Noise and privacy ---------------------------------------------
    _ft("noise_walls", "noise", "unit", "Knocked on the shared walls", _enum("solid", "hollow")),
    _ft("noise_floor", "noise", "unit", "Floor", _enum("top", "middle", "ground")),
    _ft("noise_neighbours", "noise", "unit", "Neighbours", _multi("above", "below", "side")),
    _ft(
        "noise_adjacent",
        "noise",
        "unit",
        "Adjacent to",
        _multi("elevator", "stairwell", "trash_chute", "laundry", "parking", "mechanical"),
    ),
    _ck(
        "noise_front_door",
        "noise",
        "unit",
        "Front door doesn't open onto a high-traffic area",
        "thorough",
    ),
    _ck(
        "noise_window_facing",
        "noise",
        "unit",
        "Windows don't face another unit's windows",
        "thorough",
    ),
    _im("noise_quietness", "noise", "unit", "Quietness", RATING, "quick"),
    _notes("noise"),
    # -- 11. Measurements and storage --------------------------------------
    _ft("space_living_dims", "space", "unit", "Living room size, ft by ft", TEXT),
    _ft("space_bed1_dims", "space", "unit", "Bedroom 1 size, ft by ft", TEXT),
    _ft("space_bed2_dims", "space", "unit", "Bedroom 2 size, ft by ft", TEXT, "thorough"),
    _ft("space_front_door_width", "space", "unit", "Front door width", _num("in"), "thorough"),
    _ck("space_couch_fits", "space", "unit", "The stairwell or elevator can handle a couch"),
    _ck("space_coat_closet", "space", "unit", "Coat or linen closet", "thorough"),
    _im("space_layout", "space", "unit", "Layout works for how you live", RATING),
    _ft("space_awkward", "space", "unit", "Awkward or wasted space", TEXT, "thorough"),
    _notes("space"),
    # -- 12. Safety and security -------------------------------------------
    _ft("safety_smoke_detectors", "safety", "unit", "Smoke detectors", INT, "quick"),
    _ck("safety_co_detector", "safety", "unit", "CO detector", "quick"),
    _ck("safety_sprinklers", "safety", "unit", "Sprinklers or an extinguisher", "thorough"),
    _ck("safety_deadbolt", "safety", "unit", "Deadbolt on the entry door", "quick"),
    _ck("safety_peephole", "safety", "unit", "Peephole or camera", "thorough"),
    _ck(
        "safety_ground_windows", "safety", "unit", "Ground-floor windows lock securely", "thorough"
    ),
    _ck("safety_two_exits", "safety", "unit", "Two exit routes from the unit and the building"),
    _ck(
        "safety_secure_entry",
        "safety",
        "property",
        "Secure building entry — fob, code or buzzer",
        "quick",
    ),
    _ck(
        "safety_lot_lighting",
        "safety",
        "property",
        "Exterior and lot are well lit",
        help="If you toured by day, drive by at night",
    ),
    _ft("safety_packages", "safety", "property", "How package delivery is secured", TEXT),
    _ck("safety_cameras", "safety", "property", "Cameras in the common areas", "thorough"),
    _im("safety_felt", "safety", "property", "Felt safety", RATING, "quick"),
    _notes("safety", "property"),
    # -- 13. Building, parking and amenities -------------------------------
    _im("bldg_common_areas", "building", "property", "Hallways, stairwells and laundry", RATING),
    _im("bldg_trash_area", "building", "property", "Trash and recycling area", RATING),
    _ck("bldg_mailboxes", "building", "property", "Mailboxes are secure"),
    _ck("bldg_elevator", "building", "property", "Elevator working", "thorough"),
    _ck(
        "bldg_grounds",
        "building",
        "property",
        "Grounds maintained, no obvious deferred maintenance",
    ),
    _ft(
        "bldg_parking_type",
        "building",
        "property",
        "Parking",
        _enum("assigned", "first_come", "street", "garage"),
        "quick",
    ),
    _ft("bldg_parking_cost", "building", "property", "Parking cost", MONEY, "quick"),
    _ck("bldg_guest_parking", "building", "property", "Guest parking", "thorough"),
    _ft("bldg_snow_removal", "building", "property", "Snow removal handled by", TEXT, "thorough"),
    _qn(
        "bldg_snow_piles",
        "building",
        "property",
        "Where does the plowed snow get piled?",
        "thorough",
        help="Does it block your spot?",
    ),
    _ck("bldg_bike_storage", "building", "property", "Bike storage", "thorough"),
    _ft(
        "bldg_extra_storage_cost",
        "building",
        "property",
        "Extra storage unit, per month",
        MONEY,
        "thorough",
    ),
    _ft(
        "bldg_amenities",
        "building",
        "property",
        "Amenities",
        _multi("gym", "pool", "clubhouse", "rooftop", "coworking", "ev_charging", "other"),
    ),
    _ck("bldg_saw_amenities", "building", "property", "Actually saw them"),
    _ft("bldg_amenity_fee", "building", "property", "Amenity fee, per month", MONEY),
    _ft(
        "bldg_amenity_fee_required",
        "building",
        "property",
        "Amenity fee is",
        _enum("optional", "mandatory"),
    ),
    _notes("building", "property"),
    # -- 14. Pets ----------------------------------------------------------
    _ft("pets_allowed", "pets", "property", "Pets allowed", _enum("yes", "no"), "quick"),
    _ft("pets_types", "pets", "property", "Types and limits", TEXT),
    _ft("pets_max", "pets", "property", "Maximum number", INT),
    _ft("pets_restrictions", "pets", "property", "Weight or breed restrictions", TEXT),
    _ft("pets_onetime_fee", "pets", "property", "One-time fee", MONEY),
    _ft("pets_deposit", "pets", "property", "Deposit", MONEY),
    _ft(
        "pets_deposit_refundable", "pets", "property", "Pet deposit refundable", _enum("yes", "no")
    ),
    _ft("pets_rent", "pets", "property", "Pet rent, per month", MONEY),
    _ck("pets_green_space", "pets", "property", "Green space nearby", "thorough"),
    _ck(
        "pets_other_pets",
        "pets",
        "property",
        "Other tenants' pets — any noise or smell?",
        "thorough",
    ),
    _notes("pets", "property"),
    # -- 15. Red flags — personal, tallied across the team -----------------
    _im(
        "flag_agent_evasive",
        "red_flags",
        "property",
        "Agent rushed, dodged, or wouldn't show the actual unit",
        FLAG,
        "quick",
    ),
    _im(
        "flag_pressure",
        "red_flags",
        "property",
        "Pressure to apply on the spot or pay a hold fee today",
        FLAG,
        "quick",
    ),
    _im(
        "flag_contradiction",
        "red_flags",
        "property",
        "Something the agent said contradicted the listing",
        FLAG,
        "quick",
    ),
    _im(
        "flag_common_areas_worse",
        "red_flags",
        "property",
        "Common areas noticeably worse than the unit shown",
        FLAG,
    ),
    _im("flag_vacancies", "red_flags", "property", "Many vacant units, or high turnover", FLAG),
    _im(
        "flag_fresh_paint",
        "red_flags",
        "property",
        "Fresh paint or caulk in one isolated spot",
        FLAG,
    ),
    _im(
        "flag_pests",
        "red_flags",
        "property",
        "Pest traps, glue boards or droppings visible",
        FLAG,
        "quick",
    ),
    _im(
        "flag_latches",
        "red_flags",
        "property",
        "Doors or windows that won't latch",
        FLAG,
        help="Possible settling",
    ),
    _im("flag_details", "red_flags", "property", "Details", TEXT),
    # -- 16. Money ---------------------------------------------------------
    _qn(
        "money_total_monthly",
        "money",
        "unit",
        "What is the total monthly cost — rent plus every mandatory fee?",
        "quick",
        is_critical=True,
    ),
    _qn(
        "money_utilities_included",
        "money",
        "unit",
        "Which utilities are included?",
        "quick",
        is_critical=True,
    ),
    _qn(
        "money_utility_history",
        "money",
        "unit",
        "Can I see 12 months of actual utility bills for this unit?",
        help="For this unit — not a building average",
    ),
    _qn(
        "money_fees_refundable",
        "money",
        "property",
        "Deposit, application fee, admin fee — and is the application fee "
        "refundable if I'm denied?",
        "quick",
        is_critical=True,
    ),
    _qn(
        "money_deposit_nonrefundable", "money", "property", "What makes the deposit non-refundable?"
    ),
    _ft("money_move_in_total", "money", "unit", "Move-in total", MONEY),
    _qn(
        "money_concession_amortized",
        "money",
        "property",
        "Is any move-in special amortized across the lease?",
        help="That is what makes the renewal jump",
    ),
    _ft(
        "money_payment_method",
        "money",
        "property",
        "Rent payment",
        _enum("portal", "check", "ach"),
        "thorough",
    ),
    _ft("money_convenience_fee", "money", "property", "Convenience fee", MONEY, "thorough"),
    _ft("money_late_fee", "money", "property", "Late fee", MONEY, "thorough"),
    _ft("money_grace_days", "money", "property", "Grace period", _int("days"), "thorough"),
    _notes("money"),
    # -- 17. Lease, renewal and exit ---------------------------------------
    _qn("lease_lengths", "lease", "property", "What lease lengths are available?", "quick"),
    _ft("lease_mtm_premium", "lease", "property", "Month-to-month premium", MONEY, "thorough"),
    _qn(
        "lease_renewal_increase",
        "lease",
        "property",
        "How much did rent increase for renewing tenants this year?",
        "quick",
        is_critical=True,
    ),
    _qn(
        "lease_notice",
        "lease",
        "property",
        "How much notice must I give to not renew, and what happens if I miss it?",
        "quick",
        is_critical=True,
    ),
    _qn("lease_early_termination", "lease", "property", "What is the early-termination penalty?"),
    _qn(
        "lease_auto_moveout_charges",
        "lease",
        "property",
        "What charges are automatic at move-out regardless of condition?",
        "quick",
        is_critical=True,
    ),
    _ft("lease_deposit_return_days", "lease", "property", "Deposit return timeline", _int("days")),
    _qn("lease_sublet", "lease", "property", "What is the subletting policy?", "thorough"),
    _qn("lease_guests", "lease", "property", "What is the long-term guest policy?", "thorough"),
    _ft("lease_entry_notice_hrs", "lease", "property", "Landlord entry notice", _int("hrs")),
    _qn("lease_alterations", "lease", "property", "Rules on painting, mounting TVs and shelves?"),
    _qn(
        "lease_smoking",
        "lease",
        "property",
        "Is the building smoke-free, does that include marijuana, and how is it enforced?",
        "quick",
        is_critical=True,
    ),
    _ft("lease_quiet_hours", "lease", "property", "Quiet hours", TEXT, "thorough"),
    _ft("lease_insurance_min", "lease", "property", "Renters insurance minimum", TEXT, "thorough"),
    _ck(
        "lease_blank_copy",
        "lease",
        "property",
        "Requested a blank copy of the lease before applying",
    ),
    _ck("lease_move_in_inspection", "lease", "property", "Move-in inspection form provided"),
    # -- 18. Application and screening -------------------------------------
    _qn(
        "app_requirements",
        "application",
        "property",
        "What are the income and credit requirements?",
        "quick",
        is_critical=True,
    ),
    _ft("app_fee", "application", "property", "Application fee", MONEY, "quick"),
    _ft(
        "app_fee_refundable", "application", "property", "Refundable if denied", _enum("yes", "no")
    ),
    _qn(
        "app_guarantor",
        "application",
        "property",
        "Is a guarantor or co-signer accepted, and on what terms?",
        "thorough",
    ),
    _qn(
        "app_count_in",
        "application",
        "property",
        "How many applications are already in on this unit?",
        "thorough",
    ),
    _qn(
        "app_hold", "application", "property", "Can the unit be held, and at what cost?", "thorough"
    ),
    _ft("app_decision_days", "application", "property", "Decision turnaround", _int("days")),
    _qn("app_disqualifiers", "application", "property", "What would disqualify an application?"),
    # -- 19. Building history and operations -------------------------------
    _qn(
        "hist_bed_bugs",
        "history",
        "property",
        "Has this unit or building had bed bugs in the last two years?",
        "quick",
        is_critical=True,
        help="And what is the treatment protocol?",
    ),
    _qn(
        "hist_maintenance",
        "history",
        "property",
        "How do maintenance requests work, what is the typical turnaround, "
        "and is there a 24/7 emergency line?",
        "quick",
        is_critical=True,
    ),
    _qn(
        "hist_vacancy",
        "history",
        "unit",
        "How long has this unit been vacant, and why did the last tenant leave?",
        "quick",
        is_critical=True,
    ),
    _qn("hist_pest_schedule", "history", "property", "What is the pest-control schedule?"),
    _qn(
        "hist_leaks", "history", "unit", "Any leaks, burst pipes, backups or flooding in this unit?"
    ),
    _qn("hist_ice_dams", "history", "property", "Any ice dams or roof leaks?", "thorough"),
    _ft(
        "hist_hvac_age",
        "history",
        "unit",
        "Furnace/AC age and last filter change",
        TEXT,
        "thorough",
    ),
    _qn("hist_rekeyed", "history", "property", "Are the locks re-keyed between tenants?"),
    _qn(
        "hist_break_ins", "history", "property", "Any break-ins or package theft in the last year?"
    ),
    _qn(
        "hist_noise_complaints",
        "history",
        "unit",
        "Any noise complaints on file for this unit?",
        "thorough",
    ),
    _ft("hist_management", "history", "property", "Management", _enum("on_site", "off_site")),
    _qn(
        "hist_renovations",
        "history",
        "property",
        "What was renovated or replaced, and when?",
        "thorough",
    ),
    _ck(
        "hist_lead_paint",
        "history",
        "property",
        "Lead-paint disclosure provided",
        help="Required by law for pre-1978 buildings",
    ),
    _qn(
        "hist_planned_work",
        "history",
        "property",
        "Any planned construction or renovation during my lease?",
    ),
    _qn(
        "hist_closing_question",
        "history",
        "property",
        "Is there anything about this unit or building you'd want to know if you were me?",
        "quick",
    ),
    # -- 20. After the tour ------------------------------------------------
    _ck("follow_night_drive", "followup", "property", "Drove by at night"),
    _ck("follow_rush_hour", "followup", "property", "Checked the commute at rush hour"),
    _ck(
        "follow_street_parking",
        "followup",
        "property",
        "Checked street parking in the evening",
        "thorough",
    ),
    _ck("follow_read_lease", "followup", "property", "Read the actual lease"),
    _ft(
        "follow_tenant_said", "followup", "property", "What a current tenant said", TEXT, "thorough"
    ),
    _ck(
        "follow_internet_verified",
        "followup",
        "property",
        "Verified internet speeds at this address",
    ),
    _ck(
        "follow_claims_crosschecked",
        "followup",
        "property",
        "Cross-checked the agent's claims against reviews",
    ),
    _ck(
        "follow_repairs_in_writing", "followup", "property", "Confirmed repair promises in writing"
    ),
    _ft("follow_still_to_ask", "followup", "property", "Still need to ask", TEXT),
    # -- 21a. Verdict — this unit ------------------------------------------
    _im("verdict_price_value", "verdict_unit", "unit", "Price and value", RATING, "quick"),
    _im("verdict_condition", "verdict_unit", "unit", "Unit condition", RATING, "quick"),
    _im("verdict_size_layout", "verdict_unit", "unit", "Size and layout", RATING, "quick"),
    _im("verdict_noise", "verdict_unit", "unit", "Noise", RATING, "quick"),
    _im("verdict_light", "verdict_unit", "unit", "Light", RATING, "quick"),
    _im(
        "verdict_could_live",
        "verdict_unit",
        "unit",
        "Could you live here for a year?",
        _enum("yes", "maybe", "no"),
        "quick",
    ),
    _im(
        "verdict_call",
        "verdict_unit",
        "unit",
        "Verdict",
        _enum("apply_now", "strong_contender", "backup", "pass"),
        "quick",
    ),
    _im("verdict_loved", "verdict_unit", "unit", "What you loved", TEXT),
    _im("verdict_bothered", "verdict_unit", "unit", "What bothered you", TEXT),
    _im("verdict_dealbreakers", "verdict_unit", "unit", "Dealbreakers", TEXT, "quick"),
    # -- 21b. Verdict — the whole property ---------------------------------
    # Recorded once: you would answer these identically for every unit toured,
    # and asking three times invites sloppy answers (DESIGN §9.7, R10).
    _im("verdict_safety", "verdict_property", "property", "Felt safety", RATING, "quick"),
    _im(
        "verdict_location_commute",
        "verdict_property",
        "property",
        "Location and commute",
        RATING,
        "quick",
    ),
    _im(
        "verdict_management",
        "verdict_property",
        "property",
        "Management impression",
        RATING,
        "quick",
    ),
    _im("verdict_common_areas", "verdict_property", "property", "Common areas", RATING),
    _im("verdict_property_notes", "verdict_property", "property", "Notes on the building", TEXT),
)


# ---------------------------------------------------------------------------
# Integrity + SQL generation
# ---------------------------------------------------------------------------


def validate() -> None:
    """Fail loudly on a malformed template — these are all authoring mistakes."""
    keys = [item.key for item in TEMPLATE]
    duplicates = {key for key in keys if keys.count(key) > 1}
    if duplicates:
        raise ValueError(f"duplicate template keys: {sorted(duplicates)}")
    for item in TEMPLATE:
        if item.kind == "check" and item.value_schema:
            raise ValueError(
                f"{item.key}: a check's tri-state is implied; it takes no value_schema"
            )
        if item.kind != "check" and not item.value_schema:
            raise ValueError(f"{item.key}: {item.kind} needs a value_schema")
        if item.is_critical and item.kind not in ("question", "fact"):
            raise ValueError(f"{item.key}: only questions and facts carry is_critical")
    # A section belongs to exactly one contiguous run, so section order derives
    # from display_order without a section table.
    seen: list[str] = []
    for item in TEMPLATE:
        if not seen or seen[-1] != item.section_key:
            if item.section_key in seen:
                raise ValueError(f"section {item.section_key!r} is not contiguous")
            seen.append(item.section_key)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_json(value: dict[str, Any]) -> str:
    import json

    return _sql_literal(json.dumps(value, separators=(", ", ": "), sort_keys=True)) + "::jsonb"


def generate_template_sql() -> str:
    """The INSERT block seeding `visit_template_items` for TEMPLATE_VERSION.

    Embedded verbatim in the seeding migration; `test_visit_template.py` asserts
    the committed migration still matches, so the module and the database cannot
    drift without a failing test.
    """
    validate()
    lines = [
        "insert into visit_template_items (",
        "    key, version, section_key, display_order, tier, kind, scope,",
        "    label, help, value_schema, is_critical",
        ") values",
    ]
    rows = []
    for order, item in enumerate(TEMPLATE, start=1):
        rows.append(
            "    ("
            + ", ".join(
                [
                    _sql_literal(item.key),
                    str(TEMPLATE_VERSION),
                    _sql_literal(item.section_key),
                    str(order),
                    _sql_literal(item.tier),
                    _sql_literal(item.kind),
                    _sql_literal(item.scope),
                    _sql_literal(item.label),
                    _sql_literal(item.help) if item.help else "null",
                    _sql_json(item.value_schema),
                    "true" if item.is_critical else "false",
                ]
            )
            + ")"
        )
    lines.append(",\n".join(rows) + ";")
    return "\n".join(lines)


def sections() -> tuple[str, ...]:
    """Section keys in display order."""
    out: list[str] = []
    for item in TEMPLATE:
        if not out or out[-1] != item.section_key:
            out.append(item.section_key)
    return tuple(out)
