// DM-9: the Replay Capture, its pacing, and the promise that it writes nothing.
//
// The load-bearing test here is the last one. "A demo submission creates no
// jobs, job_events or job_stage_costs rows" is checkable literally rather than
// by inspection, because the replay never addresses the network at all — so the
// test asserts on `fetch` and on the Supabase client, not on a database.
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Capture } from "../src/features/demo/replay/capture";
import { jobAt } from "../src/features/demo/replay/capture";
import {
  __resetReplayForTests,
  replaySnapshot,
  startReplay,
} from "../src/features/demo/replay/replayEngine";
import {
  compressionFactor,
  DEFAULT_TIMING,
  describeDuration,
  planReplaySchedule,
} from "../src/features/demo/replay/replayTiming";

const TOKEN_KEY = "manzil-demo-token";

function demoToken(): string {
  const b64 = (value: object) =>
    btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${b64({ alg: "HS256" })}.${b64({
    sub: "11111111-2222-3333-4444-555555555555",
    exp: Math.floor(Date.now() / 1000) + 900,
    manzil_demo: true,
  })}.sig`;
}

/**
 * A capture shaped like a real one: uneven gaps, and a checkpoint that
 * (DESIGN §20 v3.58) animates through as an ordinary timeline beat rather than
 * parking the replay -- rendering a real prompt was cut from DM-9's scope
 * because it needed either publishing page excerpts into a world-readable
 * build artifact, or a per-checkpoint-kind allow-list.
 */
function capture(): Capture {
  return {
    version: 1,
    exported_at: "2026-08-06T00:00:00Z",
    source: {
      job_id: "job-1",
      url: "https://example.test/listing",
      property_name: "Maple Court",
      source_policy: "tiers_1_2_3",
    },
    job: {
      type: "ingest",
      cost_actual_usd: 0.12,
      attempts: 1,
      plan: null,
      warnings: [],
      real_duration_ms: 240_000,
    },
    events: [
      { offset_ms: 0, stage: "VALIDATE_URL", event: "started", detail: {} },
      { offset_ms: 400, stage: "VALIDATE_URL", event: "completed", detail: {} },
      { offset_ms: 900, stage: "FETCH", event: "started", detail: { tier: 1 } },
      { offset_ms: 61_000, stage: "FETCH", event: "completed", detail: {} },
      { offset_ms: 61_500, stage: "EXTRACT", event: "started", detail: {} },
      { offset_ms: 150_000, stage: "EXTRACT", event: "completed", detail: {} },
      { offset_ms: 151_000, stage: "VERIFY", event: "checkpoint_asked", detail: {} },
      { offset_ms: 151_800, stage: "VERIFY", event: "checkpoint_answered", detail: {} },
      { offset_ms: 152_000, stage: "VERIFY", event: "completed", detail: {} },
      { offset_ms: 402_000, stage: "SCORE", event: "started", detail: {} },
      { offset_ms: 404_000, stage: "SCORE", event: "completed", detail: {} },
    ],
    has_checkpoint: true,
    listing: { id: "listing-1", property: { name: "Maple Court" } },
  };
}

describe("replay pacing", () => {
  it("compresses the run to the requested length", () => {
    const schedule = planReplaySchedule(capture().events, { targetMs: 30_000 });
    const total = schedule[schedule.length - 1].atMs;
    // Floors move this a little; the knob is meant to be approximate, not
    // exact to the millisecond.
    expect(total).toBeGreaterThan(24_000);
    expect(total).toBeLessThan(36_000);
  });

  it("keeps the relative shape: a genuinely slow stage stays slower", () => {
    const events = capture().events;
    const schedule = planReplaySchedule(events, { variance: 0 });
    // EXTRACT really took ~88s; VALIDATE_URL took 0.4s.
    const extract = schedule[5].atMs - schedule[4].atMs;
    const validate = schedule[1].atMs - schedule[0].atMs;
    expect(extract).toBeGreaterThan(validate * 3);
  });

  it("gives every stage a visible floor", () => {
    // Asserted at the floor that was asked for. This used to allow 700 against a
    // `minGapMs` of 800 — 100ms of slack, which is exactly the size of the
    // violation the post-jitter rescale was producing (`F10`).
    const schedule = planReplaySchedule(capture().events, { minGapMs: 800 });
    const gaps = schedule.slice(1).map((entry, i) => entry.atMs - schedule[i].atMs);
    expect(Math.min(...gaps)).toBeGreaterThanOrEqual(800);
  });

  it("is jittery but reproducible for a given seed", () => {
    const a = planReplaySchedule(capture().events, { seed: 7 });
    const b = planReplaySchedule(capture().events, { seed: 7 });
    const c = planReplaySchedule(capture().events, { seed: 8 });
    expect(a.map((x) => x.atMs)).toEqual(b.map((x) => x.atMs));
    expect(a.map((x) => x.atMs)).not.toEqual(c.map((x) => x.atMs));
  });

  it("describes the compression honestly", () => {
    expect(describeDuration(240_000)).toBe("about 4 minutes");
    expect(compressionFactor(240_000, DEFAULT_TIMING.targetMs)).toBeGreaterThan(5);
  });
});

// ── The timing invariants, fuzzed ────────────────────────────────────────────
//
// The example-based tests above are all satisfied by an implementation with
// three real defects (`F9`–`F11`), because every one of them happened to use a
// capture with enough gaps and a target large enough to miss them. Examples
// pin the cases somebody thought of; these pin the properties.

/** The same mulberry32 the module uses — the fuzzer needs its own, seeded. */
function fuzzRandom(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface FuzzEvent {
  offset_ms: number;
  paused?: boolean;
}

const pauseHere = (_previous: FuzzEvent, next: FuzzEvent) => next.paused === true;

/** A well-formed capture: finite, non-decreasing offsets, occasional park. */
function wellFormedCapture(random: () => number): FuzzEvent[] {
  const count = 2 + Math.floor(random() * 11);
  const events: FuzzEvent[] = [{ offset_ms: 0 }];
  let offset = 0;
  for (let i = 1; i < count; i += 1) {
    // A mixture of scales, so the fuzzer produces both flat runs and captures
    // with one stage that dwarfs the rest.
    const scale = random() < 0.2 ? 200_000 : random() < 0.5 ? 60_000 : 1_000;
    offset += Math.floor(random() * scale);
    events.push({ offset_ms: offset, paused: random() < 0.12 });
  }
  return events;
}

function randomOptions(random: () => number) {
  const pick = <V,>(values: V[]) => values[Math.floor(random() * values.length)];
  return {
    // Deliberately includes targets far below any plausible floor budget.
    targetMs: pick([1, 50, 700, 5_000, 15_000, 35_000, 90_000, 600_000]),
    minGapMs: pick([1, 120, 700, 800, 2_000]),
    maxGapMs: pick([null, null, null, 300, 900, 4_000, 50_000]),
    maxGapFraction: pick([0.05, 0.25, 0.4, 1]),
    variance: pick([0, 0.05, 0.22, 0.6]),
    seed: Math.floor(random() * 1e9),
  };
}

/** Playback gaps paired with the recorded gap each one came from. */
function gapPairs(events: FuzzEvent[], schedule: { atMs: number }[]) {
  return events.slice(1).map((event, i) => ({
    recorded: Math.max(0, event.offset_ms - events[i].offset_ms),
    playback: schedule[i + 1].atMs - schedule[i].atMs,
    paused: event.paused === true,
  }));
}

describe("replay pacing invariants", () => {
  it("never turns a larger recorded gap into a smaller playback gap", () => {
    const random = fuzzRandom(0xa11ce);
    const violations: string[] = [];
    for (let run = 0; run < 3000 && violations.length === 0; run += 1) {
      const events = wellFormedCapture(random);
      const options = randomOptions(random);
      const pairs = gapPairs(events, planReplaySchedule(events, options, pauseHere)).filter(
        (pair) => !pair.paused,
      );
      for (const a of pairs) {
        for (const b of pairs) {
          if (a.recorded > b.recorded && a.playback < b.playback) {
            violations.push(
              `run ${run}: recorded ${a.recorded} played ${a.playback}ms but ` +
                `recorded ${b.recorded} played ${b.playback}ms`,
            );
          }
        }
      }
    }
    expect(violations).toEqual([]);
  });

  it("respects the floor after jitter and the total correction", () => {
    const random = fuzzRandom(0xb0b);
    const violations: string[] = [];
    for (let run = 0; run < 3000 && violations.length === 0; run += 1) {
      const events = wellFormedCapture(random);
      const options = randomOptions(random);
      for (const pair of gapPairs(events, planReplaySchedule(events, options, pauseHere))) {
        if (pair.paused) continue;
        if (pair.playback < options.minGapMs) {
          violations.push(`run ${run}: ${pair.playback}ms < floor ${options.minGapMs}ms`);
        }
      }
    }
    expect(violations).toEqual([]);
  });

  it("runs longer than asked rather than hiding a stage", () => {
    const random = fuzzRandom(0xc0ffee);
    const violations: string[] = [];
    for (let run = 0; run < 3000 && violations.length === 0; run += 1) {
      const events = wellFormedCapture(random);
      const options = randomOptions(random);
      const schedule = planReplaySchedule(events, options, pauseHere);
      const scheduled = gapPairs(events, schedule).filter((pair) => !pair.paused).length;
      const floorBudget = scheduled * options.minGapMs;
      const total = schedule[schedule.length - 1].atMs;
      if (total < floorBudget) {
        violations.push(`run ${run}: total ${total}ms < floor budget ${floorBudget}ms`);
      }
    }
    expect(violations).toEqual([]);
  });

  it("keeps the ceiling above the floor even for an absurd target", () => {
    // `maxGapMs` was derived from the *requested* target, so a target under the
    // floor budget produced a ceiling under the floor and the replay ran
    // shorter than asked — the opposite of what the module documents (`F11`).
    for (const targetMs of [0, 1, 10, 100]) {
      const events = [{ offset_ms: 0 }, { offset_ms: 5 }, { offset_ms: 900_000 }];
      const schedule = planReplaySchedule(events, { targetMs, minGapMs: 700 }, pauseHere);
      const gaps = gapPairs(events, schedule).map((pair) => pair.playback);
      expect(Math.min(...gaps), `targetMs=${targetMs}`).toBeGreaterThanOrEqual(700);
      expect(schedule[schedule.length - 1].atMs).toBeGreaterThan(targetMs);
    }
  });

  it("only ever moves forward, for any input at all", () => {
    const random = fuzzRandom(0xdecafb);
    const hostile: number[] = [
      NaN,
      Infinity,
      -Infinity,
      -1,
      -50_000,
      0,
      Number.MAX_SAFE_INTEGER,
      1e21,
    ];
    const cases: FuzzEvent[][] = [
      [],
      [{ offset_ms: 0 }],
      [{ offset_ms: NaN }],
      [{ offset_ms: 0 }, { offset_ms: 0 }],
      [{ offset_ms: 0 }, { offset_ms: NaN }, { offset_ms: 400 }],
      [{ offset_ms: 5_000 }, { offset_ms: 0 }], // backwards
      [{ offset_ms: 0 }, { offset_ms: 1e18 }, { offset_ms: 1e18 + 1 }],
      [{ offset_ms: 0, paused: true }, { offset_ms: 900, paused: true }],
    ];
    for (let run = 0; run < 1500; run += 1) {
      const count = 1 + Math.floor(random() * 8);
      cases.push(
        Array.from({ length: count }, () => ({
          offset_ms:
            random() < 0.35
              ? hostile[Math.floor(random() * hostile.length)]
              : Math.floor(random() * 500_000),
          paused: random() < 0.15,
        })),
      );
    }

    const violations: string[] = [];
    for (const events of cases) {
      const options = randomOptions(random);
      const schedule = planReplaySchedule(events, options, pauseHere);
      let previous = -1;
      schedule.forEach((entry, i) => {
        if (!Number.isFinite(entry.atMs)) violations.push(`atMs ${entry.atMs} at ${i}`);
        if (entry.atMs < 0) violations.push(`negative atMs ${entry.atMs} at ${i}`);
        if (entry.atMs < previous) violations.push(`went backwards at ${i}`);
        previous = entry.atMs;
      });
      // And a stage that is not a pause always takes visible time.
      gapPairs(events as FuzzEvent[], schedule).forEach((pair, i) => {
        if (!pair.paused && pair.playback <= 0) violations.push(`zero-length stage at ${i}`);
      });
    }
    expect(violations).toEqual([]);
  });

  it("does not flatten a short capture into a metronome", () => {
    // `F9`, stated as the property rather than as one example: a capture with a
    // strong shape must not schedule identically to one with no shape at all.
    // Water-filling handed each clamped gap's surplus to the rest until they
    // clamped too, so with the default quarter-of-the-run ceiling *every*
    // capture of four or fewer scheduled gaps came out a perfect metronome.
    // From three events, i.e. two scheduled gaps: with a single gap there is no
    // relative shape to lose — one beat fills the target whatever it recorded.
    for (let count = 3; count <= 8; count += 1) {
      const shaped = [{ offset_ms: 0 }];
      const flat = [{ offset_ms: 0 }];
      for (let i = 1; i < count; i += 1) {
        // One stage that genuinely dominates, which is what a real capture
        // looks like: FETCH and EXTRACT dwarf everything around them.
        shaped.push({ offset_ms: shaped[i - 1].offset_ms + (i === 2 ? 90_000 : 400) });
        flat.push({ offset_ms: 0 });
      }
      const at = (events: { offset_ms: number }[]) =>
        planReplaySchedule(events, { variance: 0 }).map((entry) => entry.atMs);
      expect(at(shaped), `${count} events`).not.toEqual(at(flat));
    }

    // The exact capture the finding names, whose schedule was byte-identical to
    // all-zeros.
    const named = [0, 400, 60_400, 150_400, 152_400].map((offset_ms) => ({ offset_ms }));
    const zeros = named.map(() => ({ offset_ms: 0 }));
    expect(planReplaySchedule(named, { variance: 0 }).map((e) => e.atMs)).not.toEqual(
      planReplaySchedule(zeros, { variance: 0 }).map((e) => e.atMs),
    );
  });
});

describe("derived job rows", () => {
  it("moves queued → running → done, never parking on a checkpoint", () => {
    const bundle = capture();
    const at = (n: number) => jobAt(bundle, n, 0).state;
    expect(at(0)).toBe("queued");
    expect(at(3)).toBe("running");
    // The checkpoint events sit at indices 6-7; the run keeps moving through
    // them rather than entering `waiting_user` (DESIGN §20 v3.58).
    const checkpointAskedIndex = bundle.events.findIndex((e) => e.event === "checkpoint_asked");
    expect(at(checkpointAskedIndex + 1)).toBe("running");
    expect(at(bundle.events.length)).toBe("done");
  });

  it("accrues cost with progress rather than arriving whole at the end", () => {
    const bundle = capture();
    const early = jobAt(bundle, 2, 0).cost_actual_usd;
    const late = jobAt(bundle, bundle.events.length, 0).cost_actual_usd;
    expect(early).toBeGreaterThan(0);
    expect(early).toBeLessThan(late);
    expect(late).toBeCloseTo(0.12, 4);
  });

  it("never surfaces a checkpoint prompt", () => {
    // No prompt is exported (DESIGN §20 v3.58): publishing one into
    // `capture.json` -- a world-readable build artifact -- could carry a page
    // excerpt or model-authored prose via `flag.note`. A capture recorded from
    // a Job that parked still animates; it just never renders a prompt.
    const bundle = capture();
    for (let n = 0; n <= bundle.events.length; n += 1) {
      expect(jobAt(bundle, n, 0).checkpoint).toBeNull();
      expect(jobAt(bundle, n, 0).checkpoint_context).toBeNull();
    }
  });

  it("derives stage_index from distinct completed stages, not from `started`", () => {
    // F2: the ingest pipeline never emits `started` at all
    // (`postgres_persistence.py` writes it only for rescore/refresh Jobs), so
    // counting it left the pipeline track frozen at the first phase for every
    // demo capture. `completed` fires once per stage and is what this counts.
    const bundle: Capture = {
      ...capture(),
      events: [
        { offset_ms: 0, stage: "VALIDATE_URL", event: "completed", detail: {} },
        { offset_ms: 100, stage: "FETCH", event: "completed", detail: {} },
        { offset_ms: 200, stage: "EXTRACT", event: "completed", detail: {} },
      ],
    };
    expect(jobAt(bundle, 1, 0).stage_index).toBe(0);
    expect(jobAt(bundle, 2, 0).stage_index).toBe(1);
    expect(jobAt(bundle, 3, 0).stage_index).toBe(2);
  });
});

describe("the replay writes nothing", () => {
  let qc: QueryClient;

  beforeEach(() => {
    vi.useFakeTimers();
    window.sessionStorage.setItem(TOKEN_KEY, demoToken());
    qc = new QueryClient();
    __resetReplayForTests();
  });

  afterEach(() => {
    __resetReplayForTests();
    vi.useRealTimers();
    vi.restoreAllMocks();
    window.sessionStorage.clear();
  });

  it("drives the whole run into the query cache without touching the network", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const bundle = capture();

    startReplay(qc, "hunt-1", bundle, { targetMs: 10_000, variance: 0 });
    // No pause to resume through: the run animates straight to completion
    // (DESIGN §20 v3.58), so one advance covers the whole capture.
    vi.advanceTimersByTime(60_000);

    expect(replaySnapshot().finished).toBe(true);
    const history = qc.getQueryData(["jobs", "hunt-1", "history"]) as { state: string }[];
    expect(history[0].state).toBe("done");
    expect(qc.getQueryData(["jobs", "hunt-1", "active"])).toEqual([]);

    // The Listing arrives on the Overview, as it would after a real run.
    const listings = qc.getQueryData(["hunt_listings", "hunt-1"]) as { id: string }[];
    expect(listings.map((l) => l.id)).toEqual(["listing-1"]);

    // The whole timeline is present for the History card.
    const events = qc.getQueryData(["job_events", "job-1"]) as unknown[];
    expect(events).toHaveLength(bundle.events.length);

    // The claim DM-9 has to make literally: no Job, no job_events, no
    // job_stage_costs — because nothing was ever sent anywhere.
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("runs to completion even when the capture recorded a checkpoint", () => {
    // A capture exported from a Job that genuinely parked is still usable —
    // the checkpoint events just animate through rather than stopping the
    // clock.
    startReplay(qc, "hunt-1", capture(), { targetMs: 10_000, variance: 0 });
    vi.advanceTimersByTime(60_000);
    expect(replaySnapshot().finished).toBe(true);
  });
});
