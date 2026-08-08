// Replay pacing (DM-9, DESIGN §20 v3.57).
//
// A real ingest takes three to five minutes. Nobody watches a demo for five
// minutes, so playback is compressed — and that compression is the one part of
// a Replay Capture that is *not* faithful to the run it records. Everything
// else in the bundle really happened; the clock is staged, and the disclosure
// says so before the visitor confirms.
//
// The design goal is not "fast" but "believably fast". Three properties matter:
//
//   1. **Relative shape survives.** EXTRACT genuinely takes far longer than
//      VALIDATE_URL, and a replay where every stage takes the same beat reads
//      as a progress bar rather than as work. Gaps are scaled proportionally,
//      so the slow stages stay slow *relative to* the fast ones.
//   2. **Nothing flashes past.** A stage that lands in 40ms is invisible, which
//      makes the pipeline look like it skipped work. Every gap gets a floor.
//   3. **It is not metronomic.** Real runs are jittery; an exactly-proportional
//      replay is subtly wrong in a way people notice without being able to say
//      why. Jitter is seeded, so tests are deterministic and two visitors do
//      not get identical pacing.
//
// Everything here is pure so it can be unit-tested without timers.

export interface ReplayTimingOptions {
  /** Total playback length, excluding time parked on a checkpoint. */
  targetMs?: number;
  /** Floor for any single gap, so no stage is invisible. */
  minGapMs?: number;
  /**
   * Ceiling for any single gap, so one slow stage cannot dominate.
   *
   * Null means "a share of `targetMs`" (see `maxGapFraction`), which is what you
   * almost always want: an absolute ceiling that made sense at a 35-second
   * target becomes a straitjacket at 15 and irrelevant at 90, and flattens the
   * relative pacing the compression exists to preserve.
   */
  maxGapMs?: number | null;
  /** Ceiling as a fraction of `targetMs`, used when `maxGapMs` is null. */
  maxGapFraction?: number;
  /** Jitter as a fraction of each gap: 0.2 means ±20%. */
  variance?: number;
  /** Seed for the jitter. Fixed value ⇒ deterministic pacing. */
  seed?: number;
}

export const DEFAULT_TIMING: Required<ReplayTimingOptions> = {
  // ~35s: long enough that the pipeline reads as real work, short enough that a
  // visitor watches it to the end. Tune here; everything else follows.
  targetMs: 35_000,
  minGapMs: 700,
  maxGapMs: null,
  // A quarter of the run in one beat is a long time to watch a single stage,
  // and still leaves EXTRACT visibly the heaviest step.
  maxGapFraction: 0.25,
  variance: 0.22,
  seed: 0x5eed,
};

/** Deterministic PRNG (mulberry32) — no dependency, and reproducible in tests. */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface TimedEvent<T> {
  event: T;
  /** Milliseconds from the start of playback. */
  atMs: number;
}

/** Anything that is not a usable number becomes the value we meant. */
function finite(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/**
 * Map recorded offsets onto playback offsets.
 *
 * `isPause` marks a gap the visitor controls rather than the clock — the wait
 * on a checkpoint. Those are excluded from the budget entirely: the real run
 * may have sat parked for an hour, and the replay simply waits for an answer.
 *
 * The guarantees, each pinned by a fuzz test in `tests/demoReplay.test.ts`:
 *
 *   1. **Order-preserving.** A larger recorded gap never becomes a smaller
 *      playback gap — including after jitter, and including when the ceiling
 *      binds. This is the checkable form of "relative shape survives".
 *   2. **The floor holds after every transformation**, jitter and the total
 *      correction included.
 *   3. **The ceiling is never below the floor.**
 *   4. **The total is never below the floor budget**, so a target too small to
 *      show every stage makes the replay run *longer* than asked rather than
 *      hiding a stage.
 *   5. **The schedule only moves forward**, for every input — single event, all
 *      zeros, one enormous gap, backwards offsets, `NaN`.
 */
export function planReplaySchedule<T extends { offset_ms: number }>(
  events: T[],
  options: ReplayTimingOptions = {},
  isPause: (previous: T, next: T) => boolean = () => false,
): TimedEvent<T>[] {
  const settings = { ...DEFAULT_TIMING, ...options };
  if (events.length === 0) return [];
  if (events.length === 1) return [{ event: events[0], atMs: 0 }];

  // A capture is data from outside this module, and options come from callers.
  // A single `NaN` offset used to propagate into every `atMs` after it and the
  // replay simply stopped advancing, with nothing on screen to say why (`F11`).
  const minGapMs = Math.max(1, finite(settings.minGapMs, DEFAULT_TIMING.minGapMs));
  const variance = Math.min(0.9, Math.max(0, finite(settings.variance, DEFAULT_TIMING.variance)));
  const fraction = Math.min(
    1,
    Math.max(0.01, finite(settings.maxGapFraction, DEFAULT_TIMING.maxGapFraction)),
  );
  const random = rng(finite(settings.seed, DEFAULT_TIMING.seed));

  // 1. Real gaps, with checkpoint waits zeroed — they are not ours to schedule.
  //    A backwards or unreadable offset contributes nothing rather than a
  //    negative gap; the cursor never goes back.
  let previousOffset = finite(events[0].offset_ms, 0);
  const gaps = events.slice(1).map((event, i) => {
    const paused = isPause(events[i], event);
    const offset = finite(event.offset_ms, previousOffset);
    const real = Math.max(0, offset - previousOffset);
    previousOffset = offset;
    return { real: paused ? 0 : real, paused };
  });

  const scheduledCount = gaps.filter((gap) => !gap.paused).length;
  if (scheduledCount === 0) {
    // Every gap is a pause: there is no clock to run.
    return events.map((event) => ({ event, atMs: 0 }));
  }
  const totalReal = gaps.reduce((sum, gap) => sum + gap.real, 0);

  // 2. Floors come out of the budget first; the rest is shared proportionally.
  //    When floors alone exceed the target the replay simply runs longer than
  //    asked — refusing to show a stage is worse than overrunning by a second.
  //
  //    The target is raised to the floor budget *before* the ceiling is derived
  //    from it. Deriving `maxGapMs` from the requested target instead is what
  //    made a small `targetMs` produce a ceiling *below* the floor, and from
  //    there the replay ran shorter than asked rather than longer (`F11`).
  const floorBudget = scheduledCount * minGapMs;
  const targetMs = Math.max(finite(settings.targetMs, DEFAULT_TIMING.targetMs), floorBudget);
  const shareable = targetMs - floorBudget;

  const derived = settings.maxGapMs === null || settings.maxGapMs === undefined;
  let maxGapMs = Math.max(
    minGapMs,
    derived ? targetMs * fraction : finite(settings.maxGapMs, targetMs * fraction),
  );
  // A *derived* ceiling at or below the mean gap is not a ceiling on outliers —
  // it is a cap every gap must sit at, because the only way to spend the budget
  // is to put all of them there. That is the metronome this module exists to
  // avoid: with `maxGapFraction` 0.25, every capture with four or fewer
  // scheduled gaps produced a schedule byte-identical to an all-zero one
  // (`F9`). Short captures have no outlier to bound, so the ceiling drops.
  // An *explicit* `maxGapMs` is an instruction and is honoured as given, even
  // when it flattens: the caller asked for a hard bound.
  if (derived && maxGapMs <= targetMs / scheduledCount) maxGapMs = Infinity;

  // Water-filling: a gap that hits the ceiling gives its surplus back to the
  // others rather than shortening the whole replay. Without this, one very slow
  // recorded stage (a 90-second EXTRACT) absorbs most of the proportional share,
  // gets clamped, and the run finishes far earlier than `targetMs` asked —
  // which makes the knob a suggestion rather than a control.
  const durations = new Array<number>(gaps.length).fill(0);
  const open = new Set<number>();
  gaps.forEach((gap, i) => {
    if (!gap.paused) open.add(i);
  });

  let budget = shareable;
  let weight = totalReal;
  for (;;) {
    let clamped = false;
    for (const i of [...open]) {
      const share = weight === 0 ? budget / open.size : (gaps[i].real / weight) * budget;
      if (minGapMs + share > maxGapMs) {
        durations[i] = maxGapMs;
        budget -= maxGapMs - minGapMs;
        weight -= gaps[i].real;
        open.delete(i);
        clamped = true;
      }
    }
    if (!clamped || open.size === 0) break;
  }
  budget = Math.max(0, budget); // an explicit ceiling can overspend it
  for (const i of open) {
    const share = weight === 0 ? budget / open.size : (gaps[i].real / weight) * budget;
    durations[i] = minGapMs + share;
  }

  // 3. Jitter, then rescale so the knob stays honest: pacing becomes irregular,
  //    total length does not drift.
  //
  //    Only the part *above the floor* is rescaled. The previous version scaled
  //    the whole gap, so a correction below 1 pushed already-floored gaps under
  //    the floor — 1371 violations in 3000 fuzzed captures (`F10`). Rescaling
  //    the surplus alone keeps both properties exactly: the floor cannot be
  //    crossed because the term added to it is never negative, and the total is
  //    restored because the surplus sums to what it was.
  const jittered = durations.map((ms, i) =>
    gaps[i].paused ? 0 : Math.max(minGapMs, ms * (1 + (random() * 2 - 1) * variance)),
  );
  const surplusOf = (values: number[]) =>
    values.reduce((sum, ms, i) => sum + (gaps[i].paused ? 0 : ms - minGapMs), 0);
  const jitteredSurplus = surplusOf(jittered);
  const correction = jitteredSurplus > 0 ? surplusOf(durations) / jitteredSurplus : 0;
  const sized = jittered.map((ms, i) =>
    gaps[i].paused ? 0 : minGapMs + (ms - minGapMs) * correction,
  );

  // 4. Jitter must not reorder the run. Two nearly-equal recorded gaps could
  //    otherwise swap, which is the one thing "relative shape survives" forbids
  //    — and it is invisible in an example-based test. The jittered *values* are
  //    kept exactly as computed, so the total is untouched; only which gap gets
  //    which value is fixed, by the rank of the recorded gap.
  const scheduledIndexes = gaps.map((_gap, i) => i).filter((i) => !gaps[i].paused);
  const byRecordedGap = [...scheduledIndexes].sort(
    (a, b) => gaps[a].real - gaps[b].real || a - b,
  );
  const ascending = scheduledIndexes.map((i) => sized[i]).sort((a, b) => a - b);
  const final = new Array<number>(gaps.length).fill(0);
  byRecordedGap.forEach((index, rank) => {
    final[index] = ascending[rank];
  });

  const timed: TimedEvent<T>[] = [{ event: events[0], atMs: 0 }];
  let cursor = 0;
  final.forEach((ms, i) => {
    // Round each step rather than the cursor: rounding a running total can lose
    // up to a millisecond off a single gap, which is enough to break the floor
    // the tests assert exactly.
    cursor += gaps[i].paused ? 0 : Math.max(minGapMs, Math.round(ms));
    timed.push({ event: events[i + 1], atMs: cursor });
  });
  return timed;
}

/** How much faster than reality this playback runs, for the disclosure text. */
export function compressionFactor(realDurationMs: number | null, plannedMs: number): number | null {
  if (!realDurationMs || plannedMs <= 0) return null;
  return realDurationMs / plannedMs;
}

/** "about 4 minutes" — the real duration, phrased for the disclosure. */
export function describeDuration(ms: number | null): string | null {
  if (!ms) return null;
  const minutes = Math.round(ms / 60_000);
  if (minutes >= 2) return `about ${minutes} minutes`;
  const seconds = Math.round(ms / 1000);
  return seconds >= 90 ? "about a minute and a half" : `about ${seconds} seconds`;
}
