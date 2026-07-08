// Render an effective criterion value (§9.3: bool | number | string | object
// with a rating | null) as short UI copy. Pure and unit-tested.
export function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "unknown";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "object") {
    const rating = (value as { rating?: unknown }).rating;
    if (typeof rating === "number") return `${rating} ★`;
    return JSON.stringify(value);
  }
  return String(value).replaceAll("_", " ");
}
