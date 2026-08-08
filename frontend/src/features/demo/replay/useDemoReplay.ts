// React binding for the replay engine (DM-9).
//
// The engine itself is module-level (`replayEngine.ts`) because two routes
// drive one run; this is the thin `useSyncExternalStore` wrapper components
// use to observe it.

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useSyncExternalStore } from "react";

import { isDemo } from "../../../lib/demo";
import type { Capture } from "./capture";
import {
  replaySnapshot,
  startReplay,
  type ReplayState,
  subscribeToReplay,
} from "./replayEngine";
import { compressionFactor, DEFAULT_TIMING, type ReplayTimingOptions } from "./replayTiming";

export interface ReplayHandle extends ReplayState {
  start: () => void;
}

export function useDemoReplay(
  huntId: string,
  options: ReplayTimingOptions & { capture?: Capture } = {},
): ReplayHandle {
  const qc = useQueryClient();
  const state = useSyncExternalStore(subscribeToReplay, replaySnapshot, replaySnapshot);
  const { capture, ...timing } = options;

  // `timing` is a fresh object each render, so it is read through a ref rather
  // than closed over: depending on it would change the callback's identity every
  // render, and its values are constants in practice.
  const timingRef = useRef(timing);
  timingRef.current = timing;

  const start = useCallback(() => {
    if (!capture || !isDemo()) return;
    startReplay(qc, huntId, capture, timingRef.current);
  }, [capture, huntId, qc]);

  return { ...state, start };
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
