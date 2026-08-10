// React binding for the replay engine (DM-9).
//
// The engine itself is module-level (`replayEngine.ts`) because a run must
// survive the component that started it unmounting; this is the thin
// `useSyncExternalStore` wrapper components use to observe it.
//
// It also owns the **slate**: which recording plays next, and how many runs the
// visit has left. Both live here rather than in the caller because the two
// facts move together — claiming a run and starting its recording is one
// action, and splitting it across a component would make a double-click able to
// spend two runs on one animation.

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useSyncExternalStore } from "react";

import { isDemo } from "../../../lib/demo";
import type { Capture } from "./capture";
import {
  claimDemoRun,
  demoSlateSnapshot,
  subscribeToDemoSlate,
  syncDemoSlateRelease,
} from "./demoSlate";
import {
  replaySnapshot,
  startReplay,
  type ReplayState,
  subscribeToReplay,
} from "./replayEngine";
import { useDemoCapture, useDemoRelease } from "./useDemoCapture";
import { compressionFactor, DEFAULT_TIMING, type ReplayTimingOptions } from "./replayTiming";

export interface ReplayHandle extends ReplayState {
  /** Play the next recording on the slate. A no-op once the slate is spent. */
  start: () => void;
  /** The recording `start` would play, for the disclosure. Null when spent. */
  next: Capture | null;
  /** Recordings this build ships. */
  total: number;
  /** Recordings not yet played this page load. */
  remaining: number;
  /** No runs left — submitting stays disabled until the visitor reloads. */
  exhausted: boolean;
  /** This build ships no recordings at all, so there is nothing to offer. */
  empty: boolean;
  /** Release or the next protected capture is still loading. */
  loading: boolean;
}

export function useDemoReplay(
  huntId: string,
  options: ReplayTimingOptions = {},
): ReplayHandle {
  const qc = useQueryClient();
  const state = useSyncExternalStore(subscribeToReplay, replaySnapshot, replaySnapshot);
  const { used } = useSyncExternalStore(
    subscribeToDemoSlate,
    demoSlateSnapshot,
    demoSlateSnapshot,
  );
  const release = useDemoRelease();
  const ordinals = release.data?.capture_ordinals ?? [];

  useEffect(() => {
    syncDemoSlateRelease(release.data?.release_id ?? null);
  }, [release.data?.release_id]);

  // Timing options are constants in practice, but the object identity is fresh
  // every render. Destructuring the primitives keeps `start` stable without a
  // ref, which matters because an unstable `start` would re-run any effect that
  // depends on it — and this one spends a run.
  const { targetMs, minGapMs, maxGapMs, maxGapFraction, variance, seed } = options;

  const total = ordinals.length;
  const remaining = Math.max(0, total - used);
  const ordinal = remaining > 0 ? (ordinals[used] ?? null) : null;
  const capture = useDemoCapture(ordinal);
  const next = capture.data ?? null;

  const start = useCallback(() => {
    if (!isDemo()) return;
    // Claim first, then play. `claimDemoRun` is the single arbiter of whether a
    // run is available, so two clicks landing in the same tick cannot both pass.
    if (!capture.data) return;
    const index = claimDemoRun(ordinals.length);
    if (index === null) return;
    if (ordinals[index] !== ordinal) return;
    startReplay(qc, huntId, capture.data, {
      targetMs,
      minGapMs,
      maxGapMs,
      maxGapFraction,
      variance,
      seed,
    });
  }, [
    capture.data,
    ordinal,
    ordinals,
    huntId,
    qc,
    targetMs,
    minGapMs,
    maxGapMs,
    maxGapFraction,
    variance,
    seed,
  ]);

  return {
    ...state,
    start,
    next,
    total,
    remaining,
    exhausted: total > 0 && remaining === 0,
    empty: release.isSuccess && total === 0,
    loading: release.isPending || (ordinal !== null && capture.isPending),
  };
}

/** Disclosure copy, computed from the capture so it cannot drift from reality. */
export function replayDisclosure(capture: Capture, options: ReplayTimingOptions = {}) {
  const targetMs = options.targetMs ?? DEFAULT_TIMING.targetMs;
  return {
    realDurationMs: capture.job.real_duration_ms,
    playbackMs: targetMs,
    speedup: compressionFactor(capture.job.real_duration_ms, targetMs),
    propertyName: capture.source.property_name,
  };
}
