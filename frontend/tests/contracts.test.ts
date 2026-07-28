import { describe, expect, it } from "vitest";

import { resolveSettings } from "../src/lib/contracts";

describe("resolveSettings", () => {
  it("defaults VISION confidence independently to low", () => {
    const settings = resolveSettings({ min_confidence: "high" });

    expect(settings.min_confidence).toBe("high");
    expect(settings.min_vision_confidence).toBe("low");
  });

  it("preserves an explicit VISION confidence threshold", () => {
    expect(resolveSettings({ min_vision_confidence: "medium" }).min_vision_confidence).toBe(
      "medium",
    );
  });
});
