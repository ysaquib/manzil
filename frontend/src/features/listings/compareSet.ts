// Compare selection (P3-13 compare view, §13.2): which Unit Group rows the
// user sent to /compare. Personal per browser per hunt — localStorage, never
// server state (§20 2026-07-19). Pure helpers here are unit-tested; the hook
// is a thin persistence wrapper.
import { useLocalStorage } from "@mantine/hooks";
import { useMemo } from "react";

import type { OverviewRow } from "./overviewRows";

/** Raise to allow wider comparisons; the page lays columns out dynamically. */
export const COMPARE_LIMIT = 3;

export interface CompareEntry {
  listingId: string;
  groupKey: string;
}

export const entryKey = (entry: CompareEntry) => `${entry.listingId}:${entry.groupKey}`;

/** Only Unit Group rows compare; listing-level (pending/no-availability) rows don't. */
export function rowEntry(row: OverviewRow): CompareEntry | null {
  return row.group === null ? null : { listingId: row.listing.id, groupKey: row.group.key };
}

export function containsEntry(entries: CompareEntry[], entry: CompareEntry): boolean {
  return entries.some((e) => entryKey(e) === entryKey(entry));
}

/** Remove if present; append if there's room; full-and-absent is a no-op. */
export function toggleEntry(
  entries: CompareEntry[],
  entry: CompareEntry,
  limit: number = COMPARE_LIMIT,
): CompareEntry[] {
  if (containsEntry(entries, entry)) {
    return entries.filter((e) => entryKey(e) !== entryKey(entry));
  }
  if (entries.length >= limit) return entries;
  return [...entries, entry];
}

/** Bulk add (m6): append the missing entries in order until the limit fills. */
export function addEntries(
  entries: CompareEntry[],
  toAdd: CompareEntry[],
  limit: number = COMPARE_LIMIT,
): CompareEntry[] {
  const next = [...entries];
  for (const entry of toAdd) {
    if (next.length >= limit) break;
    if (!containsEntry(next, entry)) next.push(entry);
  }
  return next.length === entries.length ? entries : next;
}

/** Reorder (m12): move the entry at `from` to `to`, clamped; no-op when equal. */
export function moveEntry(entries: CompareEntry[], from: number, to: number): CompareEntry[] {
  if (from < 0 || from >= entries.length) return entries;
  const target = Math.max(0, Math.min(entries.length - 1, to));
  if (target === from) return entries;
  const next = [...entries];
  const [moved] = next.splice(from, 1);
  next.splice(target, 0, moved);
  return next;
}

/** Drop entries whose row no longer exists (deleted listing, vanished group). */
export function pruneEntries(entries: CompareEntry[], validKeys: Set<string>): CompareEntry[] {
  const pruned = entries.filter((e) => validKeys.has(entryKey(e)));
  return pruned.length === entries.length ? entries : pruned;
}

/** Guard against hand-edited/stale localStorage content. */
function sanitizeEntries(value: unknown): CompareEntry[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (e): e is CompareEntry =>
      typeof e === "object" && e !== null &&
      typeof (e as CompareEntry).listingId === "string" &&
      typeof (e as CompareEntry).groupKey === "string",
  );
}

export function useCompareSet(huntId: string) {
  const [stored, setStored] = useLocalStorage<CompareEntry[]>({
    key: `manzil:compare:${huntId}`,
    defaultValue: [],
  });
  const entries = useMemo(() => sanitizeEntries(stored), [stored]);
  return {
    entries,
    isFull: entries.length >= COMPARE_LIMIT,
    has: (entry: CompareEntry | null) => entry !== null && containsEntry(entries, entry),
    toggle: (entry: CompareEntry) => setStored(toggleEntry(entries, entry)),
    addMany: (toAdd: CompareEntry[]) => setStored(addEntries(entries, toAdd)),
    move: (from: number, to: number) => setStored(moveEntry(entries, from, to)),
    remove: (entry: CompareEntry) =>
      setStored(entries.filter((e) => entryKey(e) !== entryKey(entry))),
    prune: (validKeys: Set<string>) => {
      const pruned = pruneEntries(entries, validKeys);
      if (pruned !== entries) setStored(pruned);
    },
    clear: () => setStored([]),
  };
}
