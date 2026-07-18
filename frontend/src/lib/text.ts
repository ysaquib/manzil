// Shared copy helpers. Machine tokens (interest_status, source_policy,
// value_state, …) render sentence-cased — "not_interested" → "Not interested".
export function sentenceCase(token: string): string {
  const spaced = token.replaceAll("_", " ").trim();
  return spaced.length === 0 ? spaced : spaced[0].toUpperCase() + spaced.slice(1);
}
