// Shared copy helpers. Machine tokens (interest_status, source_policy,
// value_state, …) render sentence-cased — "not_interested" → "Not interested".
export function sentenceCase(token: string): string {
  const spaced = token.replaceAll("_", " ").trim();
  return spaced.length === 0 ? spaced : spaced[0].toUpperCase() + spaced.slice(1);
}

// Filter option chips are labels, not sentences — "cats_and_dogs" reads as
// "Cats & Dogs", where sentence case demotes the second noun and looks like a
// typo (UI Decision Log 2026-07-26).
export function titleCase(token: string): string {
  return sentenceCase(token)
    .split(" ")
    .map((word) => (word.length === 0 ? word : word[0].toUpperCase() + word.slice(1)))
    .join(" ")
    .replace(/\bAnd\b/g, "&");
}
