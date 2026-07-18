// Render an effective criterion value (§9.3: bool | number | string | object
// with a rating | null) as short UI copy. Pure and unit-tested.

// Numeric criteria whose bare number is ambiguous get their unit inline.
// grocery_proximity is MINUTES by the hunt's proximity_mode (walking/driving,
// DESIGN §9.5) — not distance; future map criteria (commutes) are minutes too.
const NUMBER_FORMAT: Record<string, { prefix?: string; suffix?: string }> = {
  grocery_proximity: { suffix: " min" },
  all_in_monthly: { prefix: "$" },
  security_deposit: { prefix: "$" },
  min_lease_months: { suffix: " mo" },
  sqft: { suffix: " sqft" },
};

export function displayValue(value: unknown, criterionKey?: string): string {
  if (value === null || value === undefined) return "unknown";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") {
    const format = criterionKey ? NUMBER_FORMAT[criterionKey] : undefined;
    return `${format?.prefix ?? ""}${value.toLocaleString()}${format?.suffix ?? ""}`;
  }
  if (typeof value === "object") {
    const rating = (value as { rating?: unknown }).rating;
    if (typeof rating === "number") return `${rating} ★`;
    return JSON.stringify(value);
  }
  return String(value).replaceAll("_", " ");
}
