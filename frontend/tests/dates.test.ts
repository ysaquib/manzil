import { describe, expect, it } from "vitest";

import { dateInputValue, datePickerToIso, parseLocalDate } from "../src/lib/dates";

describe("dates", () => {
  it("round-trips a local calendar date without UTC shift", () => {
    const local = new Date(2026, 7, 15); // Aug 15 local
    expect(dateInputValue(local)).toBe("2026-08-15");
    const parsed = parseLocalDate("2026-08-15");
    expect(parsed).not.toBeNull();
    expect(dateInputValue(parsed!)).toBe("2026-08-15");
  });

  it("converts Mantine picker values to ISO date strings", () => {
    const picked = new Date(2026, 7, 15);
    expect(datePickerToIso(picked)).toBe("2026-08-15");
    expect(datePickerToIso(null)).toBeNull();
  });
});
