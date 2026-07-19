// Display units for numeric criteria whose bare number is ambiguous, keyed by
// catalog key. Shared by the rubric editor/view labels and listing value
// rendering so "10" always reads as "10 min" or "$10" everywhere.
// grocery_proximity is MINUTES by the hunt's proximity_mode (walking/driving,
// DESIGN §9.5) — not distance; future map criteria (commutes) are minutes too.
export interface UnitFormat {
  prefix?: string;
  suffix?: string;
}

export const CRITERION_UNITS: Record<string, UnitFormat> = {
  grocery_proximity: { suffix: " min" },
  all_in_monthly: { prefix: "$" },
  security_deposit: { prefix: "$" },
  min_lease_months: { suffix: " mo" },
  sqft: { suffix: " sqft" },
};

export function criterionUnit(key: string | null | undefined): UnitFormat | undefined {
  return key ? CRITERION_UNITS[key] : undefined;
}
