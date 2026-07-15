// Hand-typed mirrors of the pinned data contracts (AGENTS.md; DESIGN §8.2,
// §9.3, §10.10) that the frontend reads straight from Supabase or sends to the
// API. Mutation DTOs that the API already exposes come from generated/api.d.ts
// instead; anything typed here has no generated equivalent (see
// frontend/API_ASSUMPTIONS.md, including the two flagged contract conflicts).
// Source of truth: shared/src/manzil_shared/models.py.

// --- Rubric option (pinned, §8.2) ---

export type MatchOp = "eq" | "lt" | "lte" | "gt" | "gte" | "range" | "in" | "bool";

export interface OptionMatch {
  op: MatchOp;
  value: unknown;
}

export interface RubricOption {
  match: OptionMatch;
  delta: number;
  dealbreaker_set_score: number | null;
}

export interface NonNegotiable {
  set_score: number;
}

// --- Score breakdown (pinned, §9.3) ---

export interface GateFiring {
  key: string;
  kind: "dealbreaker" | "non_negotiable";
  set_score: number;
}

export interface BreakdownCriterion {
  key: string;
  value: unknown;
  matched: OptionMatch | null;
  delta: number;
  unknown?: boolean;
}

export interface ScoreBreakdown {
  base: number;
  total: number;
  rubric_version: number;
  clamped: boolean;
  gates: GateFiring[];
  criteria: BreakdownCriterion[];
}

// Engine clamp range (§9.3): scores land in [0, 15], base 10.
export const SCORE_MAX = 15;
export const SCORE_BASE = 10;

// --- Checkpoint prompt (pinned, §10.10) ---

export interface CheckpointPrompt {
  kind: "confirm_value" | "resolve_dedupe" | "resolve_dispute";
  question: string;
  options: string[];
  default: string | null;
  context_ref?: string | null;
}

// --- Hunt settings (pinned, §8.2) — every key defaulted, so {} is valid ---

export type SourcePolicy =
  | "trust_link"
  | "tier_1"
  | "tiers_1_2"
  | "tiers_1_2_3"
  | "tier_1_plus_official";

export const SOURCE_POLICIES: { value: SourcePolicy; label: string }[] = [
  { value: "trust_link", label: "Trust this link" },
  { value: "tier_1", label: "Cross-check (simple fetch)" },
  { value: "tiers_1_2", label: "Cross-check (up to browser)" },
  { value: "tiers_1_2_3", label: "Full cross-check" },
  { value: "tier_1_plus_official", label: "Simple fetch + official site" },
];

export interface HuntSettings {
  default_source_policy: SourcePolicy;
  cost_estimate_mode: "conservative" | "median";
  min_confidence: "low" | "medium" | "high";
  proximity_mode: "walking" | "driving";
  // Household (§9.5 v1): pet counts feed scoring; occupants is reserved for
  // future utility scaling. All integers, defaulted so {} stays valid.
  occupants: number;
  cats: number;
  dogs: number;
}

export function resolveSettings(raw: Record<string, unknown> | null | undefined): HuntSettings {
  const s = raw ?? {};
  return {
    default_source_policy: (s.default_source_policy as SourcePolicy) ?? "tiers_1_2_3",
    cost_estimate_mode: (s.cost_estimate_mode as HuntSettings["cost_estimate_mode"]) ?? "conservative",
    min_confidence: (s.min_confidence as HuntSettings["min_confidence"]) ?? "medium",
    proximity_mode: (s.proximity_mode as HuntSettings["proximity_mode"]) ?? "driving",
    occupants: (s.occupants as number) ?? 1,
    cats: (s.cats as number) ?? 0,
    dogs: (s.dogs as number) ?? 0,
  };
}

// --- Shared enums (§8.1) ---

export type ValueState = "extracted" | "manual" | "estimated" | "unknown";
export type Confidence = "high" | "medium" | "low" | "not_found";
