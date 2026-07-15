// Rubric wizard draft logic (P1-12): pure, unit-tested. Validation mirrors
// the API's jsonschema check of option matches against the criterion's
// value_schema (§9.2 — one schema, two validators, zero drift), and is_bonus
// is derived, never edited (§9.2: all deltas ≥ 0).
import type { OptionMatch, RubricOption } from "../../lib/contracts";
import type { CatalogEntry, RubricCriterion } from "./api";
import type { ValueSchema } from "./widgets/types";

// A criterion is a pure bonus when nothing about it can dock points: every
// option delta ≥ 0 and the unknown delta ≥ 0.
export function deriveIsBonus(options: RubricOption[], unknownDelta: number): boolean {
  return (
    options.length > 0 &&
    unknownDelta >= 0 &&
    options.every((o) => o.delta >= 0 && o.dealbreaker_set_score === null)
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
  return catalog.map((entry, index) => {
    const saved = existingByKey.get(entry.key);
    if (saved) return { ...saved, position: index };
    return {
      catalog_key: entry.key,
      custom_def: null,
      enabled: false,
      options: entry.default_options.map((o) => ({ ...o, match: { ...o.match } })),
      unknown_delta: 0,
      non_negotiable: null,
      is_bonus: deriveIsBonus(entry.default_options, 0),
      position: index,
    };
  });
}

function typeMatches(value: unknown, schema: ValueSchema): boolean {
  if (schema.type === "boolean") return typeof value === "boolean";
  if (schema.type === "string") return typeof value === "string";
  if (schema.type === "integer") return typeof value === "number" && Number.isInteger(value);
  return typeof value === "number";
}

function scalarError(value: unknown, schema: ValueSchema): string | null {
  if (value === null || value === undefined) return "value is required";
  if (!typeMatches(value, schema)) return `expected a ${schema.type}`;
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

// Mirrors the §9.3 match semantics the engine applies and the value_schema
// bounds the API enforces. Returns a human-readable error or null.
export function validateMatch(match: OptionMatch, schema: ValueSchema): string | null {
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
  }
}

export interface CriterionIssue {
  catalogKey: string;
  message: string;
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
    if (!criterion.enabled || criterion.catalog_key === null) continue;
    const schema = schemaByKey.get(criterion.catalog_key);
    if (!schema) continue;
    if (criterion.options.length === 0) {
      issues.push({ catalogKey: criterion.catalog_key, message: "no options defined" });
      continue;
    }
    criterion.options.forEach((option, index) => {
      const error = validateMatch(option.match, schema);
      if (error) {
        issues.push({
          catalogKey: criterion.catalog_key as string,
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
