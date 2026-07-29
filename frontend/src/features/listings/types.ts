// Read models for the tables the listings surfaces subscribe to (§8.2),
// hand-typed per frontend/API_ASSUMPTIONS.md — these rows come straight from
// Supabase, not from a generated API DTO.
import type { Confidence, ScoreBreakdown, SourcePolicy, ValueState } from "../../lib/contracts";

export interface Property {
  id: string;
  name: string;
  canonical_address: string;
  city: string | null;
  state: string | null;
  county: string | null;
  official_url: string | null;
  // §12 geocode forever-cache, written by DEDUPE only-when-null. Null until a
  // run geocodes the property — the map surfaces (§13.2) treat that as
  // "not mapped yet", never as an error.
  lat: number | null;
  lng: number | null;
}

export const INTEREST_STATUSES = [
  "interested", "not_interested", "applied", "application_rejected",
  "application_withdrawn", "offer_received", "offer_accepted", "offer_declined",
  "offer_rescinded", "unavailable",
] as const;
export type InterestStatus = (typeof INTEREST_STATUSES)[number];

export interface UnitGroupState {
  hunt_listing_id: string;
  unit_group_key: string;
  interest_status: InterestStatus | null;
  visited: boolean;
  updated_by: string;
  updated_at: string;
}

export interface PropertySource {
  id: string;
  property_id: string;
  url: string;
  site_domain: string;
  is_official: boolean;
  last_fetched_at: string | null;
  last_success_at: string | null;
}

export interface FloorPlan {
  id: string;
  property_id: string;
  source_id: string;
  plan_name: string;
  beds: number;
  baths: number;
  unit_types?: string[];
  sqft_min: number | null;
  sqft_max: number | null;
  rent_min: number | null;
  rent_max: number | null;
  deposit: number | null;
  availability_date: string | null;
  available_units: number | null;
  is_current?: boolean;
  // P3-SC2 first-class identity columns (§8.2), nullable rather than buried in
  // `raw`. The detail surface links out with `detail_url` when the Source gave
  // one and falls back to the Source's own URL.
  source_native_id?: string | null;
  detail_url?: string | null;
}

// scores has a composite PK (hunt_listing_id, floor_plan_id) — no `id` column.
export interface Score {
  hunt_listing_id: string;
  floor_plan_id: string;
  total: number;
  breakdown: ScoreBreakdown;
  rubric_version: number;
  computed_at: string;
  // §9.5 P3-9: THIS plan's composition detail (scores.all_in_components) —
  // the cell/drawer must show the rent of the plan they display, not the
  // listing-level display plan's. Optional: rows scored before the column
  // landed carry null until their next rescore.
  all_in_components?: AllInComponents | null;
  // P3-SC8: THIS plan's move-in ledger (scores.move_in_components).
  move_in_components?: MoveInComponents | null;
}

export interface Extraction {
  id: string;
  property_id: string;
  hunt_id: string | null;
  criterion_key: string;
  record_kind: "resolved";
  origin_key: string;
  target_scope: "property" | "floor_plan";
  floor_plan_id: string | null;
  applicability:
    | "specific_floor_plans"
    | "all_units"
    | "select_units"
    | "unit_scope_unspecified"
    | null;
  claim_group_id: string;
  value: unknown;
  confidence: Confidence;
  evidence_quote: string | null;
  source_id: string | null;
  model: string;
  resolution_rule: string | null;
  disputed: boolean;
  extracted_at: string;
}

export interface ResolutionCandidate {
  id: string;
  value: unknown;
  confidence: Confidence;
  evidence_quote: string | null;
  selected: boolean;
  source: { url: string; site_domain: string } | null;
}

export interface Override {
  id: string;
  hunt_listing_id: string;
  criterion_key: string;
  target_scope: "property" | "floor_plan";
  floor_plan_id: string | null;
  applicability: "specific_floor_plans" | "all_units" | null;
  value: unknown;
  user_id: string;
  note: string | null;
  created_at: string;
}

// fee_checklist has a composite PK (hunt_listing_id, fee_slot) — no `id` column.
export interface FeeEntry {
  hunt_listing_id: string;
  fee_slot: string;
  amount: number | null;
  value_state: ValueState;
  entered_by: string | null;
  evidence_ref: string | null;
  updated_at: string | null;
  // P3-SC8 per-charge decisions (§9.5). All tri-state: null is "nobody said",
  // which is what keeps a move-in total honestly Incomplete. `counted` null
  // means the machine default; `credited_amount` is the part applied to first
  // month's rent, so only the remainder is cash at move-in.
  counted?: boolean | null;
  required?: boolean | null;
  refundable?: boolean | null;
  credited_amount?: number | null;
}

// §9.5: independently revertible inclusion/cost corrections for utilities
// whose status changes the all-in composition or its disclosure.
export type UtilityName =
  | "electric"
  | "gas"
  | "water"
  | "sewer"
  | "cooling"
  | "heat"
  | "trash";

export interface UtilityOverride {
  id: string;
  hunt_listing_id: string;
  utility: UtilityName;
  /** Both correction fields null is the append-only revert tombstone. */
  included: boolean | null;
  monthly_amount: number | null;
  user_id: string;
  note: string | null;
  created_at: string;
}

// §9.5 standard fee slots, in checklist order — split monthly vs one-time
// (§20 2026-07-18): monthly fees compose into all-in; one-time fees are
// move-in costs, display-only, never composed.
export const MONTHLY_FEE_SLOTS: { slot: string; label: string }[] = [
  { slot: "parking", label: "Parking" },
  { slot: "pet_rent", label: "Pet rent" },
  { slot: "pet_rent_cat", label: "Pet rent (cat)" },
  { slot: "pet_rent_dog", label: "Pet rent (dog)" },
  { slot: "insurance_program", label: "Insurance program" },
];

export const ONE_TIME_FEE_SLOTS: { slot: string; label: string }[] = [
  { slot: "application_fee", label: "Application fee" },
  { slot: "admin", label: "Admin fee" },
  { slot: "pet_deposit", label: "Pet deposit" },
  { slot: "pet_fee", label: "Pet fee (one-time)" },
];

// §9.5 P3-SC8 ledger lines the composer always emits, ahead of the slots.
export const MOVE_IN_LINE_LABELS: Record<string, string> = {
  first_month: "First month",
  security_deposit: "Security deposit",
  application_fee: "Application fee",
  admin: "Admin fee",
  pet_deposit: "Pet deposit",
  pet_fee: "Pet fee (one-time)",
};

export const FEE_SLOTS: { slot: string; label: string }[] = [
  ...MONTHLY_FEE_SLOTS,
  ...ONE_TIME_FEE_SLOTS,
];

// §9.5 one-time fee as extracted (the `one_time_fees` extraction row).
export interface OneTimeFee {
  name: string;
  amount: number;
  basis: "per_application" | "per_person" | "per_pet" | "flat";
  refundable?: boolean | null;
}

// §9.5 P3-9: the display plan's all-in composition detail
// (hunt_listings.all_in_components) — display metadata beside the pinned
// scores.breakdown, written by ingest projection and rescore.
export interface AllInComponent {
  name: string;
  amount: number | null; // null only when tag === "unknown"
  tag: "actual" | "estimated" | "unknown";
  note?: string;
}

export interface AllInComponents {
  total: number | null; // null → the criterion scored unknown (§9.5 strict branch)
  estimated_total: number;
  components: AllInComponent[];
  badges: string[]; // fees_unverified | heat_unknown | utilities_not_estimated
  mode: string; // conservative | median
  // §9.6: a live all_in_monthly override replaced the composed total; the
  // components still show what the machine would have said.
  overridden?: boolean;
}

// §9.5 P3-SC8: one line of the move-in ledger. `amount` is this household's
// figure (basis multipliers applied); `credited` is the part applied to first
// month's rent, so the cash required is `amount - credited`.
export interface MoveInCharge {
  name: string;
  amount: number | null;
  tag: "actual" | "estimated" | "unknown";
  required: boolean;
  refundable: boolean | null;
  counted: boolean;
  credited?: number;
  note?: string;
}

// §9.5 P3-SC8 composition (hunt_listings/scores.move_in_components).
// `total` null with `incomplete` true is the honest state: the subtotal is
// displayable, but the Criterion stays unknown and it is never a lower bound.
export interface MoveInComponents {
  total: number | null;
  subtotal: number;
  refundable_total: number;
  non_refundable_total: number;
  unclassified_total: number;
  incomplete: boolean;
  charges: MoveInCharge[];
  badges: string[];
  overridden?: boolean;
}

// One §3 Listing with the embeds the Overview reads in a single query.
export interface Listing {
  id: string;
  hunt_id: string;
  property_id: string;
  added_by: string;
  status: "active" | "archived";
  source_policy: SourcePolicy;
  single_source_reason: SingleSourceReason | null;
  pins: Record<string, string>;
  created_at: string;
  // Set when ingest/refresh found no available floor plans (§8.2); null while
  // pending or scored. A no-availability listing renders as a dimmed, null-score row.
  unavailable_at: string | null;
  all_in_components: AllInComponents | null;
  move_in_components?: MoveInComponents | null;
  property: Property & { floor_plans: FloorPlan[]; sources: PropertySource[] };
  scores: Score[];
}

export type SingleSourceReason =
  | "trust_link"
  | "discover_exhausted"
  | "discover_failed";
