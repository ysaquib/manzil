// Shared match-operator labels and read-only formatting for rubric view mode.
// The editor imports op metadata from here so labels stay in sync.
//
// View-label conventions (rubric read-only option rows — DESIGN §20 2026-07-10):
// - `eq` and `bool`: no operator word — "equals"/"is" are the default and add
//   noise in a scan table (show "2 br" or "yes", not "equals 2 br").
// - `lt` / `gt`: symbols (`<`, `>`) — shorter than words, unambiguous in context.
// - `range` / `in`: keep words ("between …", "any of …") — symbols would be jargon.
// Editor dropdowns still use OP_LABEL_SHORT (words + symbols where helpful).
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
};

/** Compact labels for the operator Select in edit mode. */
export const OP_LABEL_SHORT: Record<MatchOp, string> = {
  eq: "equals",
  lt: "<",
  lte: "≤",
  gt: ">",
  gte: "≥",
  range: "between",
  in: "any of",
  bool: "is",
};

export function opsForSchema(schema: ValueSchema): MatchOp[] {
  if (schema.type === "boolean") return ["bool"];
  if (schema.enum) return ["eq", "in"];
  return ["eq", "lt", "lte", "gt", "gte", "range"];
}

function formatScalar(value: unknown): string {
  if (value === null || value === undefined) return "…";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return value.toLocaleString();
  return String(value).replaceAll("_", " ");
}

/** Human-readable match label for rubric view cards. See file-header conventions. */
export function formatMatchLabel(match: OptionMatch, _schema: ValueSchema): string {
  switch (match.op) {
    case "eq":
      return formatScalar(match.value);
    case "bool":
      return formatScalar(match.value);
    case "lt":
      return `< ${formatScalar(match.value)}`;
    case "lte":
      return `≤ ${formatScalar(match.value)}`;
    case "gt":
      return `> ${formatScalar(match.value)}`;
    case "gte":
      return `≥ ${formatScalar(match.value)}`;
    case "range": {
      if (!Array.isArray(match.value) || match.value.length !== 2) return "between …";
      const [lo, hi] = match.value as unknown[];
      return `between ${formatScalar(lo)} and ${formatScalar(hi)}`;
    }
    case "in": {
      if (!Array.isArray(match.value) || match.value.length === 0) return "any of …";
      const members = (match.value as unknown[]).map(formatScalar).join(", ");
      return `any of ${members}`;
    }
  }
}
