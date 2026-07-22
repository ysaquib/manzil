// Shared match-operator labels and read-only formatting for rubric view mode.
// The editor imports op metadata from here so labels stay in sync.
//
// View-label conventions (rubric read-only option rows — DESIGN §20 2026-07-10):
// - `eq` and `bool`: no operator word — "equals"/"is" are the default and add
//   noise in a scan table (show "2 br" or "yes", not "equals 2 br").
// - `lt` / `lte` / `gt` / `gte`: symbols (`<`, `≤`, `>`, `≥`) — shorter than
//   words, unambiguous in context.
// - `range` / `in`: keep words ("between …", "any of …") — symbols would be jargon.
// - Numeric values carry their display unit (lib/criterionUnits) so thresholds
//   read as "between 10 and 20 min", never a bare "between 10 and 20".
import { criterionUnit, type UnitFormat } from "../../lib/criterionUnits";
import type { MatchOp, OptionMatch } from "../../lib/contracts";
import type { ValueSchema } from "./widgets/types";

export const OP_LABEL: Record<MatchOp, string> = {
  eq: "equals",
  lt: "less than",
  lte: "less than or equal to",
  gt: "greater than",
  gte: "greater than or equal to",
  range: "between",
  in: "any of",
  bool: "is",
  contains_any: "contains any",
  contains_all: "contains all",
};

/** Compact labels for the operator Select in edit mode. */
export const OP_LABEL_SHORT: Record<MatchOp, string> = {
  eq: "=",
  lt: "<",
  lte: "≤",
  gt: ">",
  gte: "≥",
  range: "between",
  in: "any of",
  bool: "is",
  contains_any: "contains any",
  contains_all: "contains all",
};

/** Plain-word gloss shown next to the symbol in the editor's op dropdown. */
export const OP_LABEL_WORD: Record<MatchOp, string> = {
  eq: "exactly",
  lt: "less than",
  lte: "at most",
  gt: "more than",
  gte: "at least",
  range: "between",
  in: "any of",
  bool: "is",
  contains_any: "contains any",
  contains_all: "contains all",
};

// Numeric ops in number-line order (< ≤ = ≥ >), then the compound "between" —
// reads as a scale instead of the arbitrary eq/lt/lte/gt/gte grouping.
export function opsForSchema(schema: ValueSchema): MatchOp[] {
  if (schema.type === "array") return ["contains_any", "contains_all"];
  if (schema.type === "boolean") return ["bool"];
  if (schema.enum) return ["eq", "in"];
  return ["lt", "lte", "eq", "gte", "gt", "range"];
}

function formatScalar(value: unknown, unit?: UnitFormat): string {
  if (value === null || value === undefined) return "…";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number")
    return `${unit?.prefix ?? ""}${value.toLocaleString()}${unit?.suffix ?? ""}`;
  return String(value).replaceAll("_", " ");
}

/** Human-readable match label for rubric view cards. See file-header conventions. */
export function formatMatchLabel(match: OptionMatch, criterionKey?: string | null): string {
  const unit = criterionUnit(criterionKey);
  switch (match.op) {
    case "eq":
      return formatScalar(match.value, unit);
    case "bool":
      return formatScalar(match.value);
    case "lt":
      return `< ${formatScalar(match.value, unit)}`;
    case "lte":
      return `≤ ${formatScalar(match.value, unit)}`;
    case "gt":
      return `> ${formatScalar(match.value, unit)}`;
    case "gte":
      return `≥ ${formatScalar(match.value, unit)}`;
    case "range": {
      if (!Array.isArray(match.value) || match.value.length !== 2) return "between …";
      const [lo, hi] = match.value as unknown[];
      // Suffix units read once at the end ("between 10 and 20 min"); prefix
      // units repeat per number ("between $1,800 and $2,000").
      return `between ${formatScalar(lo, unit && { prefix: unit.prefix })} and ${formatScalar(hi, unit)}`;
    }
    case "in": {
      if (!Array.isArray(match.value) || match.value.length === 0) return "any of …";
      const members = (match.value as unknown[]).map((member) => formatScalar(member)).join(", ");
      return `any of ${members}`;
    }
    case "contains_any":
    case "contains_all": {
      if (!Array.isArray(match.value) || match.value.length === 0) {
        return match.op === "contains_any" ? "contains any …" : "contains all …";
      }
      const members = (match.value as unknown[]).map((member) => formatScalar(member)).join(", ");
      return `${match.op === "contains_any" ? "contains any" : "contains all"} ${members}`;
    }
  }
}
