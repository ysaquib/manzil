// Rubric wizard draft logic (P1-12): pure, unit-tested. Validation mirrors
// the API's jsonschema check of option matches against the criterion's
// value_schema (§9.2 — one schema, two validators, zero drift), and is_bonus
// is derived, never edited (§9.2: all deltas ≥ 0).
import type { MatchOp, OptionMatch, RubricOption } from "../../lib/contracts";
import type { CatalogEntry, RubricCriterion } from "./api";
import { isTypedMultiClaimKey } from "./typedMultiClaim";
import type { ValueSchema } from "./widgets/types";

/** Catalog seed rows omit null dealbreaker_set_score; treat absent as off. */
export function normalizeRubricOption(option: RubricOption): RubricOption {
  return {
    ...option,
    match: { ...option.match },
    dealbreaker_set_score: option.dealbreaker_set_score ?? null,
  };
}

export function isOptionDealbreaker(option: RubricOption): boolean {
  return option.dealbreaker_set_score != null;
}

// A criterion is a pure bonus when nothing about it can dock points: every
// option delta ≥ 0 and the unknown delta ≥ 0.
export function deriveIsBonus(options: RubricOption[], unknownDelta: number): boolean {
  return (
    options.length > 0 &&
    unknownDelta >= 0 &&
    options.every((o) => o.delta >= 0 && !isOptionDealbreaker(o))
  );
}

// Seed the wizard: one draft criterion per catalog entry, keeping anything the
// hunt already saved and defaulting the rest from catalog default_options
// (disabled until toggled on).
export function initDraft(
  catalog: CatalogEntry[],
  existing: RubricCriterion[],
): RubricCriterion[] {
  const existingByKey = new Map(
    existing.filter((c) => c.catalog_key !== null).map((c) => [c.catalog_key as string, c]),
  );
  const catalogDraft = catalog.map((entry, index) => {
    const saved = existingByKey.get(entry.key);
    if (saved) {
      return {
        ...saved,
        position: index,
        options: saved.options.map(normalizeRubricOption),
      };
    }
    const options = entry.default_options.map(normalizeRubricOption);
    return {
      catalog_key: entry.key,
      custom_def: null,
      enabled: false,
      options,
      unknown_delta: 0,
      non_negotiable: null,
      is_bonus: deriveIsBonus(options, 0),
      position: index,
    };
  });
  const custom = existing
    .filter((criterion) => criterion.custom_def !== null)
    .map((criterion, index) => ({
      ...criterion,
      position: catalog.length + index,
      options: criterion.options.map(normalizeRubricOption),
    }));
  return [...catalogDraft, ...custom];
}

function typeMatches(value: unknown, schema: ValueSchema): boolean {
  if (schema.type === "array") return Array.isArray(value);
  if (schema.type === "boolean") return typeof value === "boolean";
  if (schema.type === "string") return typeof value === "string";
  if (schema.type === "integer") return typeof value === "number" && Number.isInteger(value);
  return typeof value === "number";
}

function scalarError(value: unknown, schema: ValueSchema): string | null {
  if (schema.type === "object") {
    // Mirrors the API's `_validate_option_schema` and the scoring engine's
    // `_comparable()` (§9.3): ordered ops against an object-typed fact (e.g.
    // management_reviews) compare on its numeric "rating" field, not the
    // object itself.
    const ratingSchema = schema.properties?.rating;
    return ratingSchema ? scalarError(value, ratingSchema) : "unsupported object criterion";
  }
  if (value === null || value === undefined) return "value is required";
  if (!typeMatches(value, schema)) return `expected a ${schema.type}`;
  if (schema.type === "string" && schema.format === "date") {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value as string);
    const parsed = match
      ? new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
      : null;
    if (
      !match ||
      parsed?.getUTCFullYear() !== Number(match[1]) ||
      parsed.getUTCMonth() !== Number(match[2]) - 1 ||
      parsed.getUTCDate() !== Number(match[3])
    ) {
      return "expected a valid date";
    }
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum)
      return `must be ≥ ${schema.minimum}`;
    if (schema.maximum !== undefined && value > schema.maximum)
      return `must be ≤ ${schema.maximum}`;
  }
  if (schema.enum && !schema.enum.includes(value as string | number))
    return `must be one of: ${schema.enum.join(", ")}`;
  return null;
}

function arrayError(value: unknown, schema: ValueSchema): string | null {
  if (!Array.isArray(value) || value.length === 0) return "needs at least one value";
  if (schema.minItems !== undefined && value.length < schema.minItems)
    return `needs at least ${schema.minItems} value(s)`;
  if (schema.maxItems !== undefined && value.length > schema.maxItems)
    return `allows at most ${schema.maxItems} value(s)`;
  if (schema.uniqueItems && new Set(value).size !== value.length) return "values must be unique";
  const itemSchema = schema.items;
  if (!itemSchema) return "array schema is missing items";
  for (const member of value) {
    const error = scalarError(member, itemSchema);
    if (error) return error;
  }
  return null;
}

// Mirrors the §9.3 match semantics the engine applies and the value_schema
// bounds the API enforces. Returns a human-readable error or null.
export function validateMatch(match: OptionMatch, schema: ValueSchema): string | null {
  if (schema.type === "array") {
    if (match.op !== "contains_any" && match.op !== "contains_all")
      return "array criteria use contains any or contains all";
    return arrayError(match.value, schema);
  }
  if (
    schema.type === "string" &&
    schema.format === "date" &&
    match.op !== "lt" &&
    match.op !== "gt" &&
    match.op !== "range"
  ) {
    return "date criteria use before, after, or between";
  }
  switch (match.op) {
    case "bool":
      if (schema.type !== "boolean") return "bool match on a non-boolean criterion";
      return scalarError(match.value, schema);
    case "eq":
      return scalarError(match.value, schema);
    case "lt":
    case "lte":
    case "gt":
    case "gte":
      if (schema.type === "boolean") return `${match.op} match on a boolean criterion`;
      return scalarError(match.value, schema);
    case "range": {
      if (!Array.isArray(match.value) || match.value.length !== 2)
        return "range needs [low, high]";
      const [lo, hi] = match.value as unknown[];
      const loError = scalarError(lo, schema);
      if (loError) return loError;
      const hiError = scalarError(hi, schema);
      if (hiError) return hiError;
      if ((lo as number | string) > (hi as number | string)) return "range low exceeds high";
      return null;
    }
    case "in": {
      if (!Array.isArray(match.value) || match.value.length === 0)
        return "in needs at least one value";
      for (const member of match.value as unknown[]) {
        const error = scalarError(member, schema);
        if (error) return error;
      }
      return null;
    }
    case "contains_any":
    case "contains_all":
      return `${match.op} match on a non-array criterion`;
  }
}

function arrayOptionsCanOverlap(left: OptionMatch, right: OptionMatch): boolean {
  const setOps: MatchOp[] = ["contains_any", "contains_all"];
  return (
    setOps.includes(left.op) &&
    setOps.includes(right.op) &&
    Array.isArray(left.value) &&
    left.value.length > 0 &&
    Array.isArray(right.value) &&
    right.value.length > 0
  );
}

/** Non-blocking save-time warnings: ordered options remain valid, but the first
 * match wins. Any two set-containment predicates can overlap when a fact
 * contains the union of their configured members, even when those members are
 * disjoint. */
export function overlapWarnings(
  draft: RubricCriterion[],
  catalog: CatalogEntry[],
): CriterionIssue[] {
  const schemaByKey = new Map(catalog.map((entry) => [entry.key, entry.value_schema]));
  const labelByKey = new Map(catalog.map((entry) => [entry.key, entry.label]));
  const warnings: CriterionIssue[] = [];

  for (const criterion of draft) {
    if (!criterion.enabled || criterion.catalog_key === null) continue;
    const key = criterion.catalog_key;
    const schema = schemaByKey.get(key);
    if (schema?.type !== "array") continue;

    if (isTypedMultiClaimKey(key)) {
      if (criterion.options.length >= 2) {
        const label = labelByKey.get(key) ?? key;
        warnings.push({
          catalogKey: key,
          tone: "info",
          message: `${label} can match multiple advertised types; only the first matching option in this order scores. Put your most preferred match first.`,
        });
      }
      continue;
    }

    const overlappingPairs: string[] = [];
    for (let left = 0; left < criterion.options.length; left += 1) {
      for (let right = left + 1; right < criterion.options.length; right += 1) {
        if (arrayOptionsCanOverlap(criterion.options[left].match, criterion.options[right].match)) {
          overlappingPairs.push(`${left + 1} and ${right + 1}`);
        }
      }
    }
    if (overlappingPairs.length > 0) {
      warnings.push({
        catalogKey: key,
        tone: "review",
        message: `options ${overlappingPairs.join(", ")} overlap; first match wins`,
      });
    }
  }

  const enabledKeys = new Set(
    draft
      .filter((criterion) => criterion.enabled && criterion.catalog_key !== null)
      .map((criterion) => criterion.catalog_key),
  );
  if (enabledKeys.has("flooring_materials") && enabledKeys.has("flooring_quality")) {
    warnings.push({
      catalogKey: "flooring_materials",
      tone: "review",
      message:
        "Flooring materials and Flooring quality are both enabled; review their points to avoid double-weighting flooring.",
    });
  }
  if (enabledKeys.has("year_built") && enabledKeys.has("kitchen_quality")) {
    warnings.push({
      catalogKey: "year_built",
      tone: "review",
      message:
        "Year built and Kitchen quality are both enabled; review their points to avoid double-weighting building age and unit condition.",
    });
  }
  if (enabledKeys.has("is_renovated") && enabledKeys.has("kitchen_quality")) {
    warnings.push({
      catalogKey: "is_renovated",
      tone: "review",
      message:
        "Renovated unit and Kitchen quality are both enabled; review their points to avoid double-weighting renovation and kitchen condition.",
    });
  }
  return warnings;
}

export interface CriterionIssue {
  catalogKey: string;
  message: string;
  tone?: "info" | "review";
}

// Validate every enabled criterion's options against its value_schema — the
// same gate the API applies on PUT, so wizard output that passes here passes
// there (P1-12 done-when).
export function validateDraft(
  draft: RubricCriterion[],
  catalog: CatalogEntry[],
): CriterionIssue[] {
  const schemaByKey = new Map(catalog.map((entry) => [entry.key, entry.value_schema]));
  const issues: CriterionIssue[] = [];
  for (const criterion of draft) {
    if (!criterion.enabled) continue;
    const key = criterion.catalog_key ?? criterion.custom_def?.key;
    if (!key) continue;
    const schema =
      criterion.catalog_key !== null
        ? schemaByKey.get(criterion.catalog_key)
        : criterion.custom_def?.value_schema;
    if (!schema) continue;
    if (criterion.options.length === 0) {
      issues.push({ catalogKey: key, message: "no options defined" });
      continue;
    }
    criterion.options.forEach((option, index) => {
      const error = validateMatch(option.match, schema);
      if (error) {
        issues.push({
          catalogKey: key,
          message: `option ${index + 1}: ${error}`,
        });
      }
    });
  }
  return issues;
}

// The PUT payload: enabled criteria plus any saved-but-disabled ones, with
// derived is_bonus stamped and positions compacted.
export function draftToPayload(draft: RubricCriterion[]): RubricCriterion[] {
  return draft.map((criterion, index) => ({
    ...criterion,
    is_bonus: deriveIsBonus(criterion.options, criterion.unknown_delta),
    position: index,
  }));
}

// Per-criterion dirty check backing the card's "Modified" indicator and the
// sticky save bar's dirty-labels list. `position` is excluded: it reflects
// this criterion's slot in the draft array, not an edit the user made to it.
export function isCriterionDirty(criterion: RubricCriterion, baseline: RubricCriterion): boolean {
  const strip = (c: RubricCriterion) => {
    const { position: _position, ...rest } = c;
    return { ...rest, is_bonus: deriveIsBonus(c.options, c.unknown_delta) };
  };
  return JSON.stringify(strip(criterion)) !== JSON.stringify(strip(baseline));
}
