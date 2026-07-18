import { describe, expect, it } from "vitest";

import type { OptionMatch } from "../../lib/contracts";
import { formatMatchLabel, opsForSchema } from "./matchLabels";
import type { ValueSchema } from "./widgets/types";

const numberSchema: ValueSchema = { type: "number", minimum: 0 };
const boolSchema: ValueSchema = { type: "boolean" };
const enumSchema: ValueSchema = { type: "string", enum: ["2_br", "3_br"] };

describe("formatMatchLabel", () => {
  it("formats scalar ops with view-label conventions", () => {
    expect(formatMatchLabel({ op: "eq", value: "2_br" })).toBe("2 br");
    expect(formatMatchLabel({ op: "lt", value: 2000 })).toBe("< 2,000");
    expect(formatMatchLabel({ op: "lte", value: 2000 })).toBe("≤ 2,000");
    expect(formatMatchLabel({ op: "gt", value: 800 })).toBe("> 800");
    expect(formatMatchLabel({ op: "gte", value: 800 })).toBe("≥ 800");
    expect(formatMatchLabel({ op: "bool", value: true })).toBe("yes");
    expect(formatMatchLabel({ op: "bool", value: false })).toBe("no");
  });

  it("formats range and in ops", () => {
    const range: OptionMatch = { op: "range", value: [800, 1200] };
    expect(formatMatchLabel(range)).toBe("between 800 and 1,200");

    const multi: OptionMatch = { op: "in", value: ["2_br", "3_br"] };
    expect(formatMatchLabel(multi)).toBe("any of 2 br, 3 br");
  });

  it("uses placeholder for incomplete values", () => {
    expect(formatMatchLabel({ op: "eq", value: null })).toBe("…");
    expect(formatMatchLabel({ op: "range", value: [null, null] })).toBe(
      "between … and …",
    );
    expect(formatMatchLabel({ op: "in", value: [] })).toBe("any of …");
  });
});

describe("opsForSchema", () => {
  it("returns ops appropriate to schema type", () => {
    expect(opsForSchema(boolSchema)).toEqual(["bool"]);
    expect(opsForSchema(enumSchema)).toEqual(["eq", "in"]);
    expect(opsForSchema(numberSchema)).toEqual(["eq", "lt", "lte", "gt", "gte", "range"]);
  });
});
