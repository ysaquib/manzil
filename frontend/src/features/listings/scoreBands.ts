import { SCORE_BASE, SCORE_MAX } from "../../lib/contracts";

const COLORS = [
  "scoreHighest", "scoreHigh", "scoreGood", "scoreMid", "scoreLow", "scorePoor", "scorePoorest",
] as const;
const LABELS = [
  "Exceptional Match", "Strong Match", "Acceptable Match", "Weak Match", "Poor Match", "Unacceptable", "Unacceptable",
] as const;

// Band index 0..6 from total/base, inclusive-lower thresholds (5/5,4/5,…).
// Anchored on the §9.3 engine domain (base 10) so color and label agree.
// IMPORTANT: the `max > 0 ? … : 0` guard is copied VERBATIM from the original
// scoreColor so behavior is byte-for-byte preserved — including the base=0
// edge, where total/0 = NaN falls through every check to band 6 (poorest).
// Do NOT "simplify" it to `base > 0`; that regresses ScoreCell's existing
// "does not divide by zero" test (NaN→poorest becomes 0→poor).
export function scoreBand(total: number, base = SCORE_BASE, max = SCORE_MAX): number {
  const pct = max > 0 ? total / base : 0;
  if (pct >= 5 / 5) return 0;
  if (pct >= 4 / 5) return 1;
  if (pct >= 3 / 5) return 2;
  if (pct >= 2 / 5) return 3;
  if (pct >= 1 / 5) return 4;
  if (pct >= 0 / 5) return 5;
  return 6;
}

export function scoreColor(total: number, base = SCORE_BASE, max = SCORE_MAX): string {
  return COLORS[scoreBand(total, base, max)];
}

export function scoreLabel(total: number): string {
  return LABELS[scoreBand(total)];
}

// Half-point deltas are common (§8.2); 9.5 must not read as 10.
export function formatScore(total: number): string {
  return Number.isInteger(total) ? String(total) : total.toFixed(1);
}
