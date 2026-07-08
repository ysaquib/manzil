import { describe, expect, it } from "vitest";

import { BoolWidget } from "./BoolWidget";
import { EnumWidget } from "./EnumWidget";
import { NumberWidget } from "./NumberWidget";
import { selectWidget } from "./widgetForSchema";

describe("selectWidget", () => {
  it("boolean schema -> BoolWidget", () => {
    expect(selectWidget({ type: "boolean" })).toBe(BoolWidget);
  });

  it("string+enum schema -> EnumWidget", () => {
    expect(selectWidget({ type: "string", enum: ["a", "b"] })).toBe(EnumWidget);
  });

  it("integer schema -> NumberWidget", () => {
    expect(selectWidget({ type: "integer", minimum: 0, maximum: 5 })).toBe(NumberWidget);
  });

  it("number schema -> NumberWidget", () => {
    expect(selectWidget({ type: "number" })).toBe(NumberWidget);
  });
});
