// Optimistic answers and the offline queue (VC-6).
//
// These pin the two rules that make a tour survive a dead signal: an answer
// appears the moment it is tapped, and a pending row is never mistaken for a
// saved one.
import { describe, expect, it } from "vitest";

import { applyOptimisticEntries, isOptimisticEntry } from "../src/features/visits/api";
import type { VisitEntry } from "../src/features/visits/types";

type Input = Parameters<typeof applyOptimisticEntries>[1][number];

function saved(partial: Partial<VisitEntry>): VisitEntry {
  return {
    id: "server-1",
    visit_id: "v1",
    item_key: "kitchen_disposal",
    is_custom: false,
    visit_unit_id: null,
    owner_user_id: null,
    author_user_id: "you",
    value: "ok",
    answer_text: null,
    note: null,
    prev_entry_id: null,
    created_at: "2026-07-30T10:00:00Z",
    ...partial,
  };
}

const input = (partial: Partial<Input> = {}): Input =>
  ({ item_key: "kitchen_disposal", is_custom: false, ...partial }) as Input;

describe("applyOptimisticEntries", () => {
  it("shows an answer immediately, because offline the round trip never comes", () => {
    const next = applyOptimisticEntries([], [input({ value: "problem" })], "v1", "me");
    expect(next).toHaveLength(1);
    expect(next[0]!.value).toBe("problem");
    expect(next[0]!.author_user_id).toBe("me");
  });

  it("replaces the identity it targets rather than piling up beside it", () => {
    // Mirrors current_visit_entries: newest per (item, unit, owner) wins.
    const next = applyOptimisticEntries(
      [saved({ visit_unit_id: "unit-a" })],
      [input({ visit_unit_id: "unit-a", value: "problem" })],
      "v1",
      "me",
    );
    expect(next).toHaveLength(1);
    expect(next[0]!.value).toBe("problem");
  });

  it("keeps answers for other units and other members apart", () => {
    const current = [
      saved({ id: "a", visit_unit_id: "unit-a" }),
      saved({ id: "b", visit_unit_id: "unit-b" }),
    ];
    const next = applyOptimisticEntries(
      current,
      [input({ visit_unit_id: "unit-a", value: "problem" })],
      "v1",
      "me",
    );
    expect(next).toHaveLength(2);
    expect(next.find((entry) => entry.visit_unit_id === "unit-b")!.value).toBe("ok");
  });

  it("files an Impression under its owner, matching what the server will do", () => {
    // The server sets owner_user_id itself; an optimistic row that disagreed
    // would briefly show one member's rating under another's identity.
    const next = applyOptimisticEntries(
      [],
      [input({ item_key: "verdict_noise", value: 4 })],
      "v1",
      "me",
      () => "me",
    );
    expect(next[0]!.owner_user_id).toBe("me");
  });

  it("carries a cleared answer as null rather than dropping the write", () => {
    const next = applyOptimisticEntries([saved({})], [input({ value: null })], "v1", "me");
    expect(next[0]!.value).toBeNull();
  });

  it("leaves fields the write did not mention alone", () => {
    const next = applyOptimisticEntries(
      [saved({ note: "cabinet smells" })],
      [input({ value: "problem" })],
      "v1",
      "me",
    );
    expect(next[0]!.note).toBe("cabinet smells");
  });

  it("marks its rows so nothing can claim them as a parent", () => {
    // The whole point: prev_entry_id must reference a row the server has seen.
    // Pointing it at a local-only row would fail the foreign key, or worse
    // manufacture a fork against a row that never existed.
    const next = applyOptimisticEntries([], [input({ value: "ok" })], "v1", "me");
    expect(isOptimisticEntry(next[0]!)).toBe(true);
    expect(isOptimisticEntry(saved({}))).toBe(false);
  });

  it("collapses a burst of offline taps on one item into one pending answer", () => {
    let entries = applyOptimisticEntries([], [input({ value: "ok" })], "v1", "me");
    entries = applyOptimisticEntries(entries, [input({ value: "problem" })], "v1", "me");
    entries = applyOptimisticEntries(entries, [input({ value: null })], "v1", "me");
    expect(entries).toHaveLength(1);
    expect(entries[0]!.value).toBeNull();
  });
});
