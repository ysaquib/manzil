import { describe, expect, it } from "vitest";

import {
  COMPARE_LIMIT,
  containsEntry,
  entryKey,
  pruneEntries,
  rowEntry,
  toggleEntry,
  type CompareEntry,
} from "./compareSet";
import type { OverviewRow } from "./overviewRows";

const e = (listingId: string, groupKey = "2-2"): CompareEntry => ({ listingId, groupKey });

describe("toggleEntry", () => {
  it("adds, removes, and refuses past the limit", () => {
    let entries: CompareEntry[] = [];
    entries = toggleEntry(entries, e("a"));
    entries = toggleEntry(entries, e("b"));
    entries = toggleEntry(entries, e("c"));
    expect(entries).toHaveLength(COMPARE_LIMIT);
    // Full: a new entry is a no-op…
    expect(toggleEntry(entries, e("d"))).toBe(entries);
    // …but toggling an existing one still removes it.
    expect(toggleEntry(entries, e("b")).map(entryKey)).toEqual(["a:2-2", "c:2-2"]);
  });

  it("treats the same listing's different unit groups as distinct", () => {
    const entries = toggleEntry([e("a", "1-1")], e("a", "2-2"));
    expect(entries).toHaveLength(2);
    expect(containsEntry(entries, e("a", "1-1"))).toBe(true);
  });
});

describe("pruneEntries", () => {
  it("drops vanished rows and keeps identity when nothing changed", () => {
    const entries = [e("a"), e("gone")];
    expect(pruneEntries(entries, new Set(["a:2-2"])).map(entryKey)).toEqual(["a:2-2"]);
    expect(pruneEntries(entries, new Set(["a:2-2", "gone:2-2"]))).toBe(entries);
  });
});

describe("rowEntry", () => {
  it("returns null for listing-level rows", () => {
    const row = { listing: { id: "a" }, group: null, state: null } as unknown as OverviewRow;
    expect(rowEntry(row)).toBeNull();
  });
});
