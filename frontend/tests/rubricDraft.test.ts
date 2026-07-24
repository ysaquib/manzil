import { describe, expect, it } from "vitest";

import type { RubricOption } from "../src/lib/contracts";
import type { CatalogEntry, RubricCriterion } from "../src/features/rubric/api";
import {
  deriveIsBonus,
  draftToPayload,
  initDraft,
  overlapWarnings,
  validateDraft,
  validateMatch,
} from "../src/features/rubric/rubricDraft";

const bedsEntry: CatalogEntry = {
  key: "beds",
  label: "Number of bedrooms",
  category: "unit",
  domain: "rent",
  fact_scope: "floor_plan",
  value_schema: { type: "integer", minimum: 0, maximum: 5 },
  default_options: [
    { match: { op: "eq", value: 2 }, delta: 0.5, dealbreaker_set_score: null },
    { match: { op: "eq", value: 0 }, delta: -0.5, dealbreaker_set_score: null },
  ],
  extraction_hint: "",
  requires_tool: null,
  refresh_class: "listing_details",
};

const laundryEntry: CatalogEntry = {
  key: "in_unit_laundry",
  label: "In-unit laundry",
  category: "unit",
  domain: "rent",
  fact_scope: "mixed",
  value_schema: { type: "string", enum: ["in_unit", "hookups", "on_site", "none"] },
  default_options: [{ match: { op: "eq", value: "in_unit" }, delta: 1, dealbreaker_set_score: null }],
  extraction_hint: "",
  requires_tool: null,
  refresh_class: "listing_details",
};

const catalog = [bedsEntry, laundryEntry];

function option(partial: Partial<RubricOption> = {}): RubricOption {
  return { match: { op: "eq", value: 2 }, delta: 0.5, dealbreaker_set_score: null, ...partial };
}

describe("deriveIsBonus (§9.2: all deltas ≥ 0)", () => {
  it("true when every option delta and the unknown delta are non-negative", () => {
    expect(deriveIsBonus([option({ delta: 0.5 }), option({ delta: 0 })], 0)).toBe(true);
  });
  it("false when any option delta is negative", () => {
    expect(deriveIsBonus([option({ delta: 0.5 }), option({ delta: -1 })], 0)).toBe(false);
  });
  it("false when the unknown delta docks points", () => {
    expect(deriveIsBonus([option({ delta: 0.5 })], -1)).toBe(false);
  });
  it("false with no options", () => {
    expect(deriveIsBonus([], 0)).toBe(false);
  });
});

describe("initDraft", () => {
  it("seeds every catalog entry disabled with default options", () => {
    const draft = initDraft(catalog, []);
    expect(draft).toHaveLength(2);
    expect(draft[0].enabled).toBe(false);
    expect(draft[0].options).toEqual(bedsEntry.default_options);
  });

  it("keeps saved criteria over defaults", () => {
    const saved: RubricCriterion = {
      catalog_key: "beds",
      custom_def: null,
      enabled: true,
      options: [option({ delta: 2 })],
      unknown_delta: -0.5,
      non_negotiable: null,
      is_bonus: false,
      position: 0,
    };
    const draft = initDraft(catalog, [saved]);
    expect(draft[0].enabled).toBe(true);
    expect(draft[0].options[0].delta).toBe(2);
  });
});

describe("validateMatch (mirrors the API's value_schema check)", () => {
  const intSchema = bedsEntry.value_schema;
  const enumSchema = laundryEntry.value_schema;

  it("accepts a valid eq match", () => {
    expect(validateMatch({ op: "eq", value: 2 }, intSchema)).toBeNull();
  });
  it("rejects out-of-bounds numbers", () => {
    expect(validateMatch({ op: "eq", value: 9 }, intSchema)).toMatch(/≤ 5/);
    expect(validateMatch({ op: "eq", value: -1 }, intSchema)).toMatch(/≥ 0/);
  });
  it("rejects non-integers for integer schemas", () => {
    expect(validateMatch({ op: "eq", value: 1.5 }, intSchema)).toMatch(/integer/);
  });
  it("rejects values outside the enum", () => {
    expect(validateMatch({ op: "eq", value: "garage" }, enumSchema)).toMatch(/one of/);
    expect(validateMatch({ op: "eq", value: "in_unit" }, enumSchema)).toBeNull();
  });
  it("requires [low, high] for range, ordered", () => {
    expect(validateMatch({ op: "range", value: [1, 3] }, intSchema)).toBeNull();
    expect(validateMatch({ op: "range", value: [3, 1] }, intSchema)).toMatch(/exceeds/);
    expect(validateMatch({ op: "range", value: 3 }, intSchema)).toMatch(/\[low, high\]/);
  });
  it("requires a non-empty array for in", () => {
    expect(validateMatch({ op: "in", value: ["in_unit", "hookups"] }, enumSchema)).toBeNull();
    expect(validateMatch({ op: "in", value: [] }, enumSchema)).toMatch(/at least one/);
  });
  it("rejects bool matches on non-boolean criteria", () => {
    expect(validateMatch({ op: "bool", value: true }, intSchema)).toMatch(/non-boolean/);
    expect(validateMatch({ op: "bool", value: true }, { type: "boolean" })).toBeNull();
  });

  it("validates controlled array/set matches and rejects exact equality", () => {
    const setSchema = {
      type: "array" as const,
      items: { type: "string" as const, enum: ["apartment", "townhome", "loft"] },
      minItems: 1,
      uniqueItems: true,
    };
    expect(validateMatch({ op: "contains_any", value: ["townhome"] }, setSchema)).toBeNull();
    expect(validateMatch({ op: "contains_all", value: [] }, setSchema)).toMatch(/at least one/);
    expect(validateMatch({ op: "contains_any", value: ["castle"] }, setSchema)).toMatch(/one of/);
    expect(validateMatch({ op: "eq", value: ["townhome"] }, setSchema)).toMatch(/array criteria/);
  });
});

describe("overlapWarnings", () => {
  it("warns without invalidating array options whose match spaces can overlap", () => {
    const entry: CatalogEntry = {
      ...bedsEntry,
      key: "property_types",
      category: "property",
      fact_scope: "property",
      value_schema: {
        type: "array",
        items: { type: "string", enum: ["apartment", "townhome", "loft"] },
        minItems: 1,
        uniqueItems: true,
      },
    };
    const draft = initDraft([entry], []);
    draft[0].enabled = true;
    draft[0].options = [
      option({ match: { op: "contains_any", value: ["apartment", "loft"] } }),
      option({ match: { op: "contains_all", value: ["townhome"] } }),
    ];
    expect(validateDraft(draft, [entry])).toEqual([]);
    expect(overlapWarnings(draft, [entry])[0].message).toMatch(/first match wins/);
  });
});

describe("validateDraft", () => {
  it("flags enabled criteria with invalid options; ignores disabled ones", () => {
    const draft = initDraft(catalog, []);
    draft[0].enabled = true;
    draft[0].options = [option({ match: { op: "eq", value: 99 } })];
    // draft[1] stays disabled with a valid default — no issue expected.
    const issues = validateDraft(draft, catalog);
    expect(issues).toHaveLength(1);
    expect(issues[0].catalogKey).toBe("beds");
  });

  it("flags an enabled criterion with no options", () => {
    const draft = initDraft(catalog, []);
    draft[1].enabled = true;
    draft[1].options = [];
    expect(validateDraft(draft, catalog)[0].message).toMatch(/no options/);
  });
});

describe("draftToPayload", () => {
  it("stamps derived is_bonus and compacts positions", () => {
    const draft = initDraft(catalog, []);
    draft[1].enabled = true; // laundry: single +1 option, unknown_delta 0 → bonus
    const payload = draftToPayload(draft);
    expect(payload[0].is_bonus).toBe(false); // beds has a -0.5 default option
    expect(payload[1].is_bonus).toBe(true);
    expect(payload.map((c) => c.position)).toEqual([0, 1]);
  });

  it("never labels a dealbreaker or negative unknown as a bonus", () => {
    const draft = initDraft(catalog, []);
    draft[1].options = [{
      ...draft[1].options[0],
      delta: 1,
      dealbreaker_set_score: 0,
    }];
    expect(draftToPayload(draft)[1].is_bonus).toBe(false);
    draft[1].options[0].dealbreaker_set_score = null;
    draft[1].unknown_delta = -0.5;
    expect(draftToPayload(draft)[1].is_bonus).toBe(false);
  });
});
