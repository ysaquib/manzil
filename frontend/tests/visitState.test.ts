import { describe, expect, it } from "vitest";

import type { Visit, VisitTemplateItem } from "../src/features/visits/types";
import {
  countByState,
  filterByState,
  groupIntoSections,
  isCustomUnit,
  itemInTier,
  sectionsOpenBeforeStart,
  sectionTitle,
  unitDescriptor,
  unitGroupKeysFor,
  visitState,
} from "../src/features/visits/visitState";

function stamps(
  partial: Partial<Pick<Visit, "started_at" | "ended_at" | "cancelled_at">>,
): Pick<Visit, "started_at" | "ended_at" | "cancelled_at"> {
  return {
    started_at: null,
    ended_at: null,
    cancelled_at: null,
    ...partial,
  };
}

describe("visitState", () => {
  it("derives planned when nothing has happened", () => {
    expect(visitState(stamps({}))).toBe("planned");
  });

  it("derives in_progress once started", () => {
    expect(visitState(stamps({ started_at: "2026-08-01T16:12:00Z" }))).toBe("in_progress");
  });

  it("derives completed once ended", () => {
    expect(
      visitState(stamps({ started_at: "2026-08-01T16:12:00Z", ended_at: "2026-08-01T16:54:00Z" })),
    ).toBe("completed");
  });

  it("lets cancellation outrank a tour that had already started and ended", () => {
    // A tour that happened and was then called off is cancelled, not completed —
    // ordering is the whole rule (DESIGN §9.7).
    expect(
      visitState(
        stamps({
          started_at: "2026-08-01T16:12:00Z",
          ended_at: "2026-08-01T16:54:00Z",
          cancelled_at: "2026-08-02T09:00:00Z",
        }),
      ),
    ).toBe("cancelled");
  });
});

describe("state counting and filtering", () => {
  const visits = [
    stamps({}),
    stamps({ started_at: "x" }),
    stamps({ started_at: "x", ended_at: "y" }),
    stamps({ cancelled_at: "z" }),
    stamps({}),
  ] as Visit[];

  it("counts every state plus a total", () => {
    expect(countByState(visits)).toEqual({
      all: 5,
      planned: 2,
      in_progress: 1,
      completed: 1,
      cancelled: 1,
    });
  });

  it("filters by derived state, and 'all' is a pass-through", () => {
    expect(filterByState(visits, "planned")).toHaveLength(2);
    expect(filterByState(visits, "cancelled")).toHaveLength(1);
    expect(filterByState(visits, "all")).toHaveLength(5);
  });
});

describe("unit display", () => {
  it("names the plan and group when the unit maps to a Floor Plan", () => {
    expect(unitDescriptor({ beds: 2, baths: 2, floor_plan_id: "fp1" }, "The Alder")).toBe(
      "The Alder · 2 bd / 2 ba",
    );
  });

  it("says a described unit was not advertised rather than implying it was", () => {
    expect(unitDescriptor({ beds: 1, baths: 1.5, floor_plan_id: null })).toBe(
      "1 bd / 1.5 ba · not advertised",
    );
  });

  it("treats a plan-less unit as custom", () => {
    expect(isCustomUnit({ floor_plan_id: null })).toBe(true);
    expect(isCustomUnit({ floor_plan_id: "fp1" })).toBe(false);
  });

  it("derives the Unit Group keys a visit touches, deduplicated", () => {
    expect(
      unitGroupKeysFor([
        { beds: 2, baths: 2 },
        { beds: 2, baths: 2 },
        { beds: 1, baths: 1.5 },
      ]),
    ).toEqual(["2-2", "1-1.5"]);
  });

  it("formats whole-number baths without a trailing zero, matching the DB key", () => {
    // The roll-up (VC-8) joins on this string, so "2-2" and "2-2.0" are not
    // interchangeable.
    expect(unitGroupKeysFor([{ beds: 2, baths: 2.0 }])).toEqual(["2-2"]);
  });
});

describe("tier dial", () => {
  it("is cumulative — standard includes quick, thorough includes both", () => {
    expect(itemInTier("quick", "quick")).toBe(true);
    expect(itemInTier("standard", "quick")).toBe(false);
    expect(itemInTier("quick", "standard")).toBe(true);
    expect(itemInTier("standard", "standard")).toBe(true);
    expect(itemInTier("thorough", "standard")).toBe(false);
    expect(itemInTier("thorough", "thorough")).toBe(true);
  });
});

function item(partial: Partial<VisitTemplateItem>): VisitTemplateItem {
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

describe("groupIntoSections", () => {
  const items = [
    item({ key: "p1", section_key: "prep", scope: "property", display_order: 1 }),
    item({ key: "p2", section_key: "prep", scope: "property", display_order: 2, tier: "thorough" }),
    item({ key: "k1", section_key: "kitchen", scope: "unit", display_order: 3 }),
    item({ key: "v1", section_key: "verdict_unit", scope: "unit", display_order: 4 }),
    item({ key: "v2", section_key: "verdict_property", scope: "property", display_order: 5 }),
  ];

  it("groups contiguous runs in display order", () => {
    const sections = groupIntoSections(items);
    expect(sections.map((s) => s.key)).toEqual([
      "prep",
      "kitchen",
      "verdict_unit",
      "verdict_property",
    ]);
  });

  it("sorts by display_order rather than trusting input order", () => {
    const shuffled = [items[3], items[0], items[2], items[1], items[4]];
    expect(groupIntoSections(shuffled).map((s) => s.key)).toEqual([
      "prep",
      "kitchen",
      "verdict_unit",
      "verdict_property",
    ]);
  });

  it("splits a non-contiguous section into separate runs, by contract", () => {
    // Sections are contiguous by contract — the API-side template test asserts
    // it and mergeCustomItems preserves it — so grouping deliberately does not
    // re-merge. Documented here because the symptom (two chips with the same
    // title) is otherwise a puzzle.
    const broken = [
      item({ key: "a", section_key: "kitchen", display_order: 1 }),
      item({ key: "b", section_key: "prep", display_order: 2 }),
      item({ key: "c", section_key: "kitchen", display_order: 3 }),
    ];
    expect(groupIntoSections(broken).map((s) => s.key)).toEqual(["kitchen", "prep", "kitchen"]);
  });

  it("records each section's scopes so the unit switcher can be hidden", () => {
    const sections = groupIntoSections(items);
    const prep = sections.find((s) => s.key === "prep")!;
    const kitchen = sections.find((s) => s.key === "kitchen")!;
    expect(prep.hasPropertyScoped).toBe(true);
    expect(prep.hasUnitScoped).toBe(false);
    expect(kitchen.hasUnitScoped).toBe(true);
    expect(kitchen.hasPropertyScoped).toBe(false);
  });

  it("drops items above the active tier", () => {
    const quick = groupIntoSections(items, "quick");
    expect(quick.flatMap((s) => s.items.map((i) => i.key))).not.toContain("p2");
    const thorough = groupIntoSections(items, "thorough");
    expect(thorough.flatMap((s) => s.items.map((i) => i.key))).toContain("p2");
  });

  it("opens only the property-scoped prep section before a tour starts", () => {
    const open = sectionsOpenBeforeStart(groupIntoSections(items));
    expect(open.map((s) => s.key)).toEqual(["prep"]);
    expect(open.every((s) => !s.hasUnitScoped)).toBe(true);
  });
});

describe("sectionTitle", () => {
  it("names the split verdict sections distinctly", () => {
    expect(sectionTitle("verdict_unit")).toBe("Verdict — this unit");
    expect(sectionTitle("verdict_property")).toBe("Verdict — the building");
  });

  it("falls back readably for an unknown key rather than showing a raw slug", () => {
    expect(sectionTitle("some_new_section")).toBe("some new section");
  });
});
