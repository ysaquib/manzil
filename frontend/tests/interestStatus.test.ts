import { describe, expect, it } from "vitest";

import { interestLabel, interestTone } from "../src/features/listings/interestStatus";
import { INTEREST_STATUSES } from "../src/features/listings/types";

describe("interestTone", () => {
  it("returns a Mantine palette name, never a hex value", () => {
    for (const status of INTEREST_STATUSES) {
      expect(interestTone(status)).toMatch(/^[a-z]+$/);
    }
  });

  it("covers every seeded status", () => {
    for (const status of INTEREST_STATUSES) {
      expect(interestTone(status)).toBeTruthy();
    }
  });

  it("groups the lifecycle: in the running, on them, on you, won, lost, out of play", () => {
    expect(interestTone("interested")).toBe("cyan");
    expect(interestTone("applied")).toBe("indigo");
    expect(interestTone("offer_received")).toBe("yellow");
    expect(interestTone("offer_accepted")).toBe("green");
    expect(interestTone("application_rejected")).toBe("red");
    expect(interestTone("offer_rescinded")).toBe("red");
    expect(interestTone("not_interested")).toBe("gray");
  });

  it("reserves grape for human-entered values, so no status claims it", () => {
    const tones = INTEREST_STATUSES.map(interestTone);
    expect(tones).not.toContain("grape");
  });

  it("is warm neutral when undecided", () => {
    expect(interestTone(null)).toBe("gray");
  });
});

describe("interestLabel", () => {
  it("is Title Case, matching the filter chips", () => {
    expect(interestLabel("interested")).toBe("Interested");
    expect(interestLabel("offer_received")).toBe("Offer Received");
    expect(interestLabel("not_interested")).toBe("Not Interested");
  });

  it("shortens the compound application/offer statuses", () => {
    expect(interestLabel("application_rejected")).toBe("Rejected");
    expect(interestLabel("application_withdrawn")).toBe("Withdrawn");
    expect(interestLabel("offer_rescinded")).toBe("Rescinded");
  });

  it("names the empty state", () => {
    expect(interestLabel(null)).toBe("Undecided");
  });

  it("never leaves an underscore in user-facing copy", () => {
    for (const status of INTEREST_STATUSES) {
      expect(interestLabel(status)).not.toContain("_");
    }
  });
});
