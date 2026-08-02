/** Catalog keys whose extracted facts can contain multiple typed values (§9.3). */
export const TYPED_MULTI_CRITERIA = new Set([
  "in_unit_laundry",
  "parking",
  "cooling",
]);

export function isTypedMultiClaimKey(key: string): boolean {
  return TYPED_MULTI_CRITERIA.has(key);
}
