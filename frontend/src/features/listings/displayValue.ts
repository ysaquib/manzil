// Render an effective criterion value (§9.3: bool | number | string | object
// with a rating | null) as short UI copy. Pure and unit-tested.
import { criterionUnit } from "../../lib/criterionUnits";

export function displayValue(value: unknown, criterionKey?: string): string {
  if (value === null || value === undefined) return "unknown";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") {
    const format = criterionUnit(criterionKey);
    return `${format?.prefix ?? ""}${value.toLocaleString()}${format?.suffix ?? ""}`;
  }
  if (typeof value === "object") {
    const rating = (value as { rating?: unknown }).rating;
    if (typeof rating === "number") return `${rating} ★`;
    return JSON.stringify(value);
  }
  return String(value).replaceAll("_", " ");
}
