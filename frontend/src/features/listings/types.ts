// Read models for the tables the listings surfaces subscribe to (§8.2),
// hand-typed per frontend/API_ASSUMPTIONS.md — these rows come straight from
// Supabase, not from a generated API DTO.
import type { Confidence, ScoreBreakdown, SourcePolicy, ValueState } from "../../lib/contracts";

export interface Property {
  id: string;
  name: string;
  canonical_address: string;
  official_url: string | null;
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
}

// scores has a composite PK (hunt_listing_id, floor_plan_id) — no `id` column.
export interface Score {
  hunt_listing_id: string;
  floor_plan_id: string;
  total: number;
  breakdown: ScoreBreakdown;
  rubric_version: number;
  computed_at: string;
}

export interface Extraction {
  id: string;
  property_id: string;
  hunt_id: string | null;
  criterion_key: string;
  value: unknown;
  confidence: Confidence;
  evidence_quote: string | null;
  source_id: string | null;
  model: string;
  resolution_rule: string | null;
  extracted_at: string;
}

export interface Override {
  id: string;
  hunt_listing_id: string;
  criterion_key: string;
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

// §9.5 standard fee slots, in checklist order.
export const FEE_SLOTS: { slot: string; label: string }[] = [
  { slot: "admin", label: "Admin fee" },
  { slot: "water_sewer", label: "Water / sewer billing" },
  { slot: "valet_trash", label: "Valet trash" },
  { slot: "parking", label: "Parking" },
  { slot: "pet_rent", label: "Pet rent" },
  { slot: "insurance_program", label: "Insurance program" },
];

// One §3 Listing with the embeds the Overview reads in a single query.
export interface Listing {
  id: string;
  hunt_id: string;
  property_id: string;
  added_by: string;
  status: "active" | "archived";
  source_policy: SourcePolicy;
  pins: Record<string, string>;
  created_at: string;
  property: Property & { floor_plans: FloorPlan[]; sources: PropertySource[] };
  scores: Score[];
}
