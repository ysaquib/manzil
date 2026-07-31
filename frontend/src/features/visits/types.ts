// Visit types (DESIGN §9.7). Hand-typed for the direct-Supabase reads, mirroring
// the migration's shapes; the API request/response shapes come from the
// generated OpenAPI types instead. See frontend/API_ASSUMPTIONS.md.

export type VisitState = "planned" | "in_progress" | "completed" | "cancelled";
export type VisitItemKind = "fact" | "check" | "question" | "impression";
export type VisitItemScope = "property" | "unit";
export type VisitTier = "quick" | "standard" | "thorough";

export interface VisitUnit {
  id: string;
  visit_id: string;
  /** Always human-typed — there is no advertised unit list to select from. */
  label: string;
  /** Null when the listing never advertised this unit. Normal, not an error. */
  floor_plan_id: string | null;
  beds: number;
  baths: number;
  /** Database-generated; matches the key ratings/comments/pins use. Read-only. */
  unit_group_key: string;
  display_order: number;
  created_by: string;
  created_at: string;
}

export interface Visit {
  id: string;
  hunt_id: string;
  property_id: string;
  created_by: string;
  scheduled_for: string | null;
  /** State derives from these three (see `visitState`); there is no status column. */
  started_at: string | null;
  ended_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  template_version: number;
  prefilled_from: string | null;
  created_at: string;
  visit_units: VisitUnit[];
  /** Embedded Property identity; `properties` is globally readable (§8.3). */
  property: { id: string; name: string; canonical_address: string } | null;
}

export interface VisitTemplateItem {
  key: string;
  version: number;
  section_key: string;
  display_order: number;
  tier: VisitTier;
  kind: VisitItemKind;
  scope: VisitItemScope;
  label: string;
  help: string | null;
  value_schema: Record<string, unknown>;
  is_critical: boolean;
}

/**
 * A checklist item as the runtime sees it: a template row, or a custom addition
 * normalised into the same shape (`isCustom` distinguishes them, and drives both
 * the visible "Custom" marker and the `is_custom` flag on the write).
 */
export interface VisitItem extends VisitTemplateItem {
  isCustom?: boolean;
}

export interface VisitEntry {
  id: string;
  visit_id: string;
  item_key: string;
  is_custom: boolean;
  /** Null exactly when the item is property-scoped. */
  visit_unit_id: string | null;
  /** Null for shared items; the member for an Impression. */
  owner_user_id: string | null;
  /** Always who wrote this row — the byline, even on shared items. */
  author_user_id: string;
  value: unknown;
  answer_text: string | null;
  note: string | null;
  prev_entry_id: string | null;
  created_at: string;
}

/**
 * One competing branch of an unresolved answer fork (VC-6).
 *
 * Rows sharing a `fork_parent_id` are the branches of a single conflict: each
 * author believed they were overwriting the same row, which is what happens
 * when a queued write flushes after somebody else has moved on.
 */
export interface VisitEntryConflict extends Omit<VisitEntry, "prev_entry_id"> {
  fork_parent_id: string;
}

/**
 * A figure confirmed on a Visit, offered to a Listing (VC-7, DESIGN §9.7).
 *
 * `target` names which write accepting performs: `fee_slot` upserts the fee
 * checklist in place, `override` appends to overrides. Rejecting writes only
 * the decision — the Visit's own record of what was quoted is untouched.
 */
export interface VisitFeeProposal {
  id: string;
  visit_id: string;
  /** Null when the figure is about the property rather than one door. */
  visit_unit_id: string | null;
  hunt_listing_id: string;
  target: "fee_slot" | "override";
  /** A fee slot name, or an Override criterion key. */
  target_key: string;
  amount: number;
  note: string | null;
  status: "pending" | "accepted" | "rejected";
  decided_by: string | null;
  decided_at: string | null;
  created_by: string;
  created_at: string;
}

/**
 * A Visit score for one Unit Group row (VC-8, DESIGN §9.7).
 *
 * Shown **beside** Fit, never merged into it: the Rubric score is deterministic
 * and the engine is domain-blind, while this is a human judgement from standing
 * in the room. Adjacency is what makes a 7-on-paper / 2.2-in-person listing
 * legible.
 */
export interface VisitUnitGroupScore {
  hunt_listing_id: string;
  unit_group_key: string;
  /** Out of 5. Latest tour per door, then the best door in the group. */
  score: number;
  best_visit_unit_id: string;
  best_visit_id: string;
  best_visited_at: string;
  /** How many members rated the winning door. */
  rater_count: number;
  /** Doors toured in this group — drives the "best of N" affordance. */
  unit_count: number;
}

export interface VisitCustomItem {
  id: string;
  visit_id: string;
  section_key: string;
  kind: VisitItemKind;
  scope: VisitItemScope;
  label: string;
  created_by: string;
  created_at: string;
}

export interface VisitDefect {
  id: string;
  visit_id: string;
  /** Null means the building rather than a unit — documented, not inferred. */
  visit_unit_id: string | null;
  /** Set when promoted from a failed Check rather than typed by hand. */
  from_item_key: string | null;
  title: string;
  note: string | null;
  /** Null = unrated. A promoted defect starts unrated by design. */
  severity: number | null;
  promised_in_writing: boolean;
  resolution: string | null;
  created_by: string;
  created_at: string;
  deleted_at: string | null;
}

/** A unit as the create flow holds it before the Visit exists. */
export interface DraftUnit {
  /** Client-side key; the server assigns the real id. */
  localId: string;
  label: string;
  floorPlanId: string | null;
  planName: string | null;
  beds: number;
  baths: number;
  /** True when described by hand rather than picked from a Floor Plan. */
  custom: boolean;
}
