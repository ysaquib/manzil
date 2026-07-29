// §9.5: the effective utilities-included list — the resolved Extraction plus
// active per-utility decisions (a NULL current override is a revert tombstone
// and intentionally has no effect). Shared by the Cost & fees rows and the
// group-header summary; kept pure so it can be unit-tested without React.
import type { DraftUtility } from "./draftDiff";
import type { UtilityName, UtilityOverride } from "./types";

export function effectiveUtilitiesIncluded(
  extractedIncluded: string[] | null,
  overrides: UtilityOverride[],
  drafts: Map<UtilityName, DraftUtility> = new Map(),
): string[] {
  const included = new Set(extractedIncluded ?? []);
  const names = new Set<UtilityName>([
    ...overrides.map((entry) => entry.utility),
    ...drafts.keys(),
  ]);
  for (const utility of names) {
    const server = overrides.find((entry) => entry.utility === utility);
    const decision = drafts.has(utility) ? drafts.get(utility)?.included : server?.included;
    if (decision === true) included.add(utility);
    if (decision === false) included.delete(utility);
  }
  return [...included].sort();
}
