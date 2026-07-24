import type { Property } from "./types";

/** Display label for a Property's locality — never parses free-form addresses. */
export function propertyLocationLabel(
  property: Pick<Property, "city" | "state" | "county">,
): string {
  if (property.city && property.state) return `${property.city}, ${property.state}`;
  if (property.city) return property.city;
  if (property.county && property.state) return `${property.county}, ${property.state}`;
  if (property.state) return property.state;
  return "Unknown";
}

/** Match a saved city filter token against a Property. */
export function cityFilterMatches(
  property: Pick<Property, "city" | "state" | "county">,
  token: string,
  label: string = propertyLocationLabel(property),
): boolean {
  if (token === "Unknown") return !property.city && !property.state && !property.county;
  if (token.includes(", ")) return label === token;
  return property.city === token;
}
