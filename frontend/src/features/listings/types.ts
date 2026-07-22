// Read models for the tables the listings surfaces subscribe to (§8.2),
// hand-typed per frontend/API_ASSUMPTIONS.md — these rows come straight from
// Supabase, not from a generated API DTO.
import type { Confidence, ScoreBreakdown, SourcePolicy, ValueState } from "../../lib/contracts";

export interface Property {
  id: string;
  name: string;
  canonical_address: string;
  city: string | null;
  official_url: string | null;
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
  sqft_min: number | null;
  sqft_max: number | null;
  rent_min: number | null;
  rent_max: number | null;
  deposit: number | null;
  availability_date: string | null;
  available_units: number | null;
  is_current?: boolean;
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
}

// §9.5 standard fee slots, in checklist order — split monthly vs one-time
// (§20 2026-07-18): monthly fees compose into all-in; one-time fees are
// move-in costs, display-only, never composed.
export const MONTHLY_FEE_SLOTS: { slot: string; label: string }[] = [
  { slot: "water_sewer", label: "Water / sewer billing" },
  { slot: "valet_trash", label: "Valet trash" },
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
  property: Property & { floor_plans: FloorPlan[]; sources: PropertySource[] };
  scores: Score[];
}

export type SingleSourceReason =
  | "trust_link"
  | "discover_exhausted"
  | "discover_failed";
