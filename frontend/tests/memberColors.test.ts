import { describe, expect, it } from "vitest";

import { memberColor, starColorCss } from "../src/features/collaboration/memberColors";

describe("starColorCss", () => {
  it("maps a known member token to its Mantine color var", () => {
    expect(starColorCss("moss")).toBe("var(--mantine-color-green-6)");
    expect(starColorCss("plum")).toBe("var(--mantine-color-grape-6)");
    expect(starColorCss("brick")).toBe("var(--mantine-color-red-6)");
    expect(memberColor("dusky")).toBe("var(--mantine-color-dusky-6)");
    expect(memberColor("orange")).toBe("var(--mantine-color-orange-6)");
    expect(memberColor("teal")).toBe("var(--mantine-color-teal-6)");
    expect(memberColor("cyan")).toBe("var(--mantine-color-cyan-6)");
    expect(memberColor("blue")).toBe("var(--mantine-color-blue-6)");
    expect(memberColor("indigo")).toBe("var(--mantine-color-indigo-6)");
    expect(memberColor("violet")).toBe("var(--mantine-color-violet-6)");
    expect(memberColor("pink")).toBe("var(--mantine-color-pink-6)");
  });

  it("falls back to yellow when the token is null", () => {
    expect(starColorCss(null)).toBe("var(--mantine-color-yellow-6)");
  });

  it("passes an unknown non-null value through", () => {
    expect(starColorCss("#abcdef")).toBe("#abcdef");
  });
});
