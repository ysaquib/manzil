import { describe, expect, it } from "vitest";

import { starColorCss } from "../src/features/collaboration/memberColors";

describe("starColorCss", () => {
  it("maps a known member token to its Mantine color var", () => {
    expect(starColorCss("moss")).toBe("var(--mantine-color-green-6)");
    expect(starColorCss("plum")).toBe("var(--mantine-color-grape-6)");
    expect(starColorCss("brick")).toBe("var(--mantine-color-red-6)");
  });

  it("falls back to yellow when the token is null", () => {
    expect(starColorCss(null)).toBe("var(--mantine-color-yellow-6)");
  });

  it("passes an unknown non-null value through", () => {
    expect(starColorCss("#abcdef")).toBe("#abcdef");
  });
});
