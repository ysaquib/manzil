import { describe, expect, it } from "vitest";

import { formatCalendarDay, localCalendarDay } from "../src/lib/calendarDays";

describe("calendar day labels", () => {
  it("formats YYYY-MM-DD without UTC Date parsing", () => {
    expect(formatCalendarDay("2026-08-11")).toBe("Aug 11");
  });

  it("builds the local date label from local fields", () => {
    expect(localCalendarDay(new Date(2026, 7, 11, 23, 30))).toBe("2026-08-11");
  });
});
