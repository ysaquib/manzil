import { describe, expect, it } from "vitest";

import {
  checkStateOf,
  currentAnswer,
  defaultSchemaFor,
  entryIdentity,
  indexEntries,
  isAnswered,
  meanRating,
  mergeCustomItems,
  nextCheckState,
  ownerFor,
  progressFor,
  teamAnswers,
  unitFor,
} from "../src/features/visits/entries";
import type { VisitEntry, VisitItem } from "../src/features/visits/types";

function item(partial: Partial<VisitItem> = {}): VisitItem {
  return {
    key: "k",
    version: 1,
    section_key: "kitchen",
    display_order: 1,
    tier: "standard",
    kind: "check",
    scope: "unit",
    label: "Label",
    help: null,
    value_schema: {},
    is_critical: false,
    ...partial,
  };
}

function entry(partial: Partial<VisitEntry> = {}): VisitEntry {
  return {
    id: "e1",
    visit_id: "v1",
    item_key: "k",
    is_custom: false,
    visit_unit_id: null,
    owner_user_id: null,
    author_user_id: "u1",
    value: null,
    answer_text: null,
    note: null,
    prev_entry_id: null,
    created_at: "2026-07-30T10:00:00Z",
    ...partial,
  };
}

describe("entry identity", () => {
  it("keeps a null unit distinct from a unit literally named 'null'", () => {
    expect(entryIdentity("k", null, null)).not.toBe(entryIdentity("k", "null", null));
  });

  it("cannot collide across segment boundaries", () => {
    // "a" + unit "b" must not equal item "a b" with no unit.
    expect(entryIdentity("a", "b", null)).not.toBe(entryIdentity("a b", null, null));
  });
});

describe("scope and ownership resolution", () => {
  it("attaches a unit only to unit-scoped items", () => {
    expect(unitFor(item({ scope: "unit" }), "unit-1")).toBe("unit-1");
    expect(unitFor(item({ scope: "property" }), "unit-1")).toBeNull();
  });

  it("attaches an owner only to impressions", () => {
    expect(ownerFor(item({ kind: "impression" }), "u1")).toBe("u1");
    expect(ownerFor(item({ kind: "check" }), "u1")).toBeNull();
    expect(ownerFor(item({ kind: "fact" }), "u1")).toBeNull();
    expect(ownerFor(item({ kind: "question" }), "u1")).toBeNull();
  });

  it("finds a property answer regardless of which unit is active", () => {
    const propertyItem = item({ key: "prep_reviews", scope: "property" });
    const index = indexEntries([entry({ item_key: "prep_reviews", value: "ok" })]);
    expect(currentAnswer(index, propertyItem, "unit-1", "u1")?.value).toBe("ok");
    expect(currentAnswer(index, propertyItem, "unit-2", "u1")?.value).toBe("ok");
  });

  it("keeps unit answers separate per unit", () => {
    const unitItem = item({ key: "stove", scope: "unit", kind: "fact" });
    const index = indexEntries([
      entry({ id: "a", item_key: "stove", visit_unit_id: "unit-1", value: "gas" }),
      entry({ id: "b", item_key: "stove", visit_unit_id: "unit-2", value: "electric" }),
    ]);
    expect(currentAnswer(index, unitItem, "unit-1", "u1")?.value).toBe("gas");
    expect(currentAnswer(index, unitItem, "unit-2", "u1")?.value).toBe("electric");
  });

  it("keeps impressions separate per member, so nobody overwrites anybody", () => {
    const impression = item({ key: "noise", kind: "impression", scope: "unit" });
    const index = indexEntries([
      entry({ id: "a", item_key: "noise", visit_unit_id: "u", owner_user_id: "me", value: 2 }),
      entry({ id: "b", item_key: "noise", visit_unit_id: "u", owner_user_id: "you", value: 4 }),
    ]);
    expect(currentAnswer(index, impression, "u", "me")?.value).toBe(2);
    expect(currentAnswer(index, impression, "u", "you")?.value).toBe(4);
  });
});

describe("isAnswered", () => {
  it("treats a Question as answered only by its text", () => {
    const question = item({ kind: "question" });
    expect(isAnswered(question, entry({ value: true }))).toBe(false);
    expect(isAnswered(question, entry({ answer_text: "   " }))).toBe(false);
    expect(isAnswered(question, entry({ answer_text: "No incidents" }))).toBe(true);
  });

  it("treats a null value as unanswered — that is the tombstone", () => {
    expect(isAnswered(item(), entry({ value: null }))).toBe(false);
    expect(isAnswered(item(), entry({ value: "ok" }))).toBe(true);
  });

  it("counts a zero rating as answered rather than missing", () => {
    expect(isAnswered(item({ kind: "impression" }), entry({ value: 0 }))).toBe(true);
  });

  it("is false when nothing was ever written", () => {
    expect(isAnswered(item(), undefined)).toBe(false);
  });
});

describe("progress", () => {
  it("counts only the viewer's own answers for impressions", () => {
    const items = [
      item({ key: "a", kind: "check", scope: "unit" }),
      item({ key: "b", kind: "impression", scope: "unit" }),
    ];
    const index = indexEntries([
      entry({ id: "1", item_key: "a", visit_unit_id: "u", value: "ok" }),
      // Somebody else's opinion must not count as the viewer's progress.
      entry({ id: "2", item_key: "b", visit_unit_id: "u", owner_user_id: "someone", value: 4 }),
    ]);
    expect(progressFor(items, index, "u", "me")).toEqual({ answered: 1, total: 2 });
  });
});

describe("check tri-state", () => {
  it("reads only the two real states", () => {
    expect(checkStateOf(entry({ value: "ok" }))).toBe("ok");
    expect(checkStateOf(entry({ value: "problem" }))).toBe("problem");
    expect(checkStateOf(entry({ value: null }))).toBeNull();
    expect(checkStateOf(undefined)).toBeNull();
  });

  it("clears when the active state is tapped again", () => {
    expect(nextCheckState("ok", "ok")).toBeNull();
    expect(nextCheckState("ok", "problem")).toBe("problem");
    expect(nextCheckState(null, "ok")).toBe("ok");
  });
});

describe("team aggregate", () => {
  const impression = item({ key: "noise", kind: "impression", scope: "unit" });

  it("gathers every member's rating for the active unit only", () => {
    const entries = [
      entry({ id: "1", item_key: "noise", visit_unit_id: "u1", owner_user_id: "a", value: 2 }),
      entry({ id: "2", item_key: "noise", visit_unit_id: "u1", owner_user_id: "b", value: 4 }),
      entry({ id: "3", item_key: "noise", visit_unit_id: "u2", owner_user_id: "a", value: 5 }),
    ];
    expect(teamAnswers(entries, impression, "u1")).toHaveLength(2);
  });

  it("ignores cleared answers so a tombstone doesn't drag the mean down", () => {
    const entries = [
      entry({ id: "1", item_key: "noise", visit_unit_id: "u1", owner_user_id: "a", value: 4 }),
      entry({ id: "2", item_key: "noise", visit_unit_id: "u1", owner_user_id: "b", value: null }),
    ];
    expect(meanRating(teamAnswers(entries, impression, "u1"))).toBe(4);
  });

  it("returns null rather than 0 when nobody has rated", () => {
    expect(meanRating([])).toBeNull();
  });

  it("rounds to one decimal", () => {
    const entries = [
      entry({ id: "1", item_key: "noise", visit_unit_id: "u", owner_user_id: "a", value: 2 }),
      entry({ id: "2", item_key: "noise", visit_unit_id: "u", owner_user_id: "b", value: 3 }),
      entry({ id: "3", item_key: "noise", visit_unit_id: "u", owner_user_id: "c", value: 4 }),
    ];
    expect(meanRating(teamAnswers(entries, impression, "u"))).toBe(3);
  });

  it("is empty for a non-impression, which has no per-member answers", () => {
    const entries = [entry({ item_key: "k", visit_unit_id: "u", value: "ok" })];
    expect(teamAnswers(entries, item({ kind: "check" }), "u")).toEqual([]);
  });
});

describe("custom items", () => {
  const template = [
    item({ key: "k1", section_key: "kitchen", display_order: 10 }),
    item({ key: "b1", section_key: "bathrooms", display_order: 20 }),
  ];

  it("places a custom item at the end of its own section, not the end of the list", () => {
    const merged = mergeCustomItems(
      template,
      [{ id: "c1", section_key: "kitchen", kind: "check", scope: "unit", label: "Stand mixer" }],
      1,
    );
    expect(merged.map((i) => i.key)).toEqual(["k1", "c1", "b1"]);
  });

  it("flags them so they are never mistaken for the built-in list", () => {
    const merged = mergeCustomItems(
      template,
      [{ id: "c1", section_key: "kitchen", kind: "check", scope: "unit", label: "Stand mixer" }],
      1,
    );
    expect(merged.find((i) => i.key === "c1")?.isCustom).toBe(true);
    expect(merged.find((i) => i.key === "k1")?.isCustom).toBeUndefined();
  });

  it("keeps two additions to one section in a stable order", () => {
    const merged = mergeCustomItems(
      template,
      [
        { id: "c1", section_key: "kitchen", kind: "check", scope: "unit", label: "First" },
        { id: "c2", section_key: "kitchen", kind: "check", scope: "unit", label: "Second" },
      ],
      1,
    );
    expect(merged.map((i) => i.key)).toEqual(["k1", "c1", "c2", "b1"]);
  });

  it("returns the template untouched when there are no custom items", () => {
    expect(mergeCustomItems(template, [], 1)).toBe(template);
  });

  it("gives each kind a usable default schema", () => {
    expect(defaultSchemaFor("check")).toEqual({});
    expect(defaultSchemaFor("question")).toEqual({ type: "text" });
    expect(defaultSchemaFor("impression")).toEqual({ type: "rating", max: 5 });
    expect(defaultSchemaFor("fact")).toEqual({ type: "text" });
  });
});
