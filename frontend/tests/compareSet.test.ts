import { describe, expect, it } from "vitest";

import {
  addEntries,
  COMPARE_LIMIT,
  containsEntry,
  entryKey,
  moveEntry,
  pruneEntries,
  rowEntry,
  toggleEntry,
  type CompareEntry,
} from "../src/features/listings/compareSet";
import type { OverviewRow } from "../src/features/listings/overviewRows";

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

describe("addEntries (m6 bulk send)", () => {
  it("appends missing entries in order until the limit fills", () => {
    const entries = addEntries([e("a")], [e("a"), e("b"), e("c"), e("d")]);
    expect(entries.map(entryKey)).toEqual(["a:2-2", "b:2-2", "c:2-2"]);
  });

  it("returns the same array when nothing fits or everything is present", () => {
    const full = [e("a"), e("b"), e("c")];
    expect(addEntries(full, [e("d")])).toBe(full);
    const partial = [e("a")];
    expect(addEntries(partial, [e("a")])).toBe(partial);
  });
});

describe("moveEntry (m12 reorder)", () => {
  const entries = [e("a"), e("b"), e("c")];

  it("moves an entry forward and backward", () => {
    expect(moveEntry(entries, 0, 2).map(entryKey)).toEqual(["b:2-2", "c:2-2", "a:2-2"]);
    expect(moveEntry(entries, 2, 0).map(entryKey)).toEqual(["c:2-2", "a:2-2", "b:2-2"]);
  });

  it("clamps the target and no-ops on same or invalid indexes", () => {
    expect(moveEntry(entries, 1, 99).map(entryKey)).toEqual(["a:2-2", "c:2-2", "b:2-2"]);
    expect(moveEntry(entries, 1, 1)).toBe(entries);
    expect(moveEntry(entries, -1, 0)).toBe(entries);
    expect(moveEntry(entries, 5, 0)).toBe(entries);
  });
});
