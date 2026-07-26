import { describe, expect, it } from "vitest";

import { sentenceCase, titleCase } from "../src/lib/text";

describe("sentenceCase", () => {
  it("unslugs a machine token", () => {
    expect(sentenceCase("not_interested")).toBe("Not interested");
  });

  it("survives the empty string", () => {
    expect(sentenceCase("")).toBe("");
  });
});

describe("titleCase", () => {
  it("capitalises every word, so a compound label doesn't look like a typo", () => {
    expect(titleCase("offer_received")).toBe("Offer Received");
    expect(titleCase("in_unit")).toBe("In Unit");
    expect(titleCase("window_units")).toBe("Window Units");
  });

  it("renders a coordinate compound with an ampersand", () => {
    expect(titleCase("cats_and_dogs")).toBe("Cats & Dogs");
  });

  it("leaves a single word alone beyond capitalising it", () => {
    expect(titleCase("garage")).toBe("Garage");
  });

  it("never leaves an underscore in user-facing copy", () => {
    expect(titleCase("street_only")).not.toContain("_");
  });
});
