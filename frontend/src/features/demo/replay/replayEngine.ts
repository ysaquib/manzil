// The replay engine (DM-9, DESIGN §3, §16, §20 v3.57/v3.58).
//
// Module-level rather than a hook, for the same reason `lib/demo.ts` is: it
// must survive the component that started it unmounting, and a future caller
// resuming it should not need a prop threaded from the Overview.
//
// It writes into the query cache and nowhere else. No Job, no `job_events`, no
// `job_stage_costs`, no network call of any kind — which is what lets DM-9's
// acceptance be checked literally: after a demo submission, those tables are
// untouched because nothing ever addressed them.
//
// It does not pause. An earlier version stopped the clock at a recorded
// checkpoint and waited for the visitor to "answer" it, but rendering a real
// prompt turned out to need a per-checkpoint-kind safe-field allow-list. The
// current protected publication sanitizer deliberately omits those fields
// (DESIGN §20 v3.58, see `capture.ts`), so a recorded checkpoint animates
// through as an ordinary timeline beat.

import type { QueryClient } from "@tanstack/react-query";

import type { Job, JobEvent } from "../../jobs/api";
import { eventsAt, jobAt, type Capture } from "./capture";
import { planReplaySchedule, type ReplayTimingOptions } from "./replayTiming";

export interface ReplayState {
  running: boolean;
  finished: boolean;
}

const IDLE: ReplayState = { running: false, finished: false };

let state: ReplayState = IDLE;
let listeners = new Set<() => void>();
let timer: ReturnType<typeof setTimeout> | null = null;

let active: {
  qc: QueryClient;
  huntId: string;
  capture: Capture;
  options: ReplayTimingOptions;
  schedule: ReturnType<typeof planReplaySchedule<Capture["events"][number]>>;
  startedAt: number;
  cursor: number;
} | null = null;

function emit(next: ReplayState) {
  state = next;
  listeners.forEach((listener) => listener());
}

export function subscribeToReplay(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function replaySnapshot(): ReplayState {
  return state;
}

function clearTimer() {
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
}

/** Write the run after `count` events into every key the Tasks UI reads. */
function paint(count: number) {
  if (!active) return;
  const { qc, huntId, capture, startedAt } = active;
  const job = jobAt(capture, count, startedAt);
  const events = eventsAt(capture, count, startedAt);

  const upsert = (list: Job[] = []) => [...list.filter((j) => j.id !== job.id), job];
  const isActive =
    job.state === "queued" || job.state === "running" || job.state === "waiting_user";

  qc.setQueryData<Job[]>(["jobs", huntId], upsert);
  qc.setQueryData<Job[]>(["jobs", huntId, "active"], (list = []) =>
    isActive ? upsert(list) : list.filter((j) => j.id !== job.id),
  );
  qc.setQueryData<Job[]>(["jobs", huntId, "history"], (list = []) =>
    isActive ? list.filter((j) => j.id !== job.id) : upsert(list),
  );
  qc.setQueryData<JobEvent[]>(["job_events", job.id], events);
}

/**
 * The captured Listing joins the Overview, under its real Property name --
 * idempotent, so calling it again at the end of the run (once every event has
 * applied) is a harmless no-op once `startReplay` has already published it.
 */
function publish() {
  if (!active) return;
  const { qc, huntId, capture } = active;
  qc.setQueryData<Record<string, unknown>[]>(["hunt_listings", huntId], (list = []) =>
    list.some((row) => row.id === capture.listing.id)
      ? list
      : [...list, capture.listing as Record<string, unknown>],
  );
}

function step(index: number) {
  if (!active) return;
  const { capture, schedule } = active;
  active.cursor = index + 1;
  paint(active.cursor);

  if (active.cursor >= capture.events.length) {
    publish();
    emit({ running: false, finished: true });
    return;
  }

  const delay = Math.max(0, schedule[active.cursor].atMs - schedule[index].atMs);
  timer = setTimeout(() => step(active!.cursor), delay);
}

export function startReplay(
  qc: QueryClient,
  huntId: string,
  capture: Capture,
  options: ReplayTimingOptions = {},
): void {
  clearTimer();
  active = {
    qc,
    huntId,
    capture,
    options,
    schedule: planReplaySchedule(capture.events, options),
    startedAt: Date.now(),
    cursor: 0,
  };
  emit({ running: true, finished: false });
  // A real submission's Listing row appears on the Overview immediately
  // (a placeholder created at submit time, filled in as the pipeline runs),
  // not only once the run finishes. `publish()` here matches that: the
  // recorded Listing joins the Overview, under its real Property name, as
  // soon as the replay starts rather than only once it completes — the
  // concession being that it shows the finished capture, not a true
  // in-progress placeholder, since that is the only shape the capture holds.
  publish();
  paint(0);
  // A chain of one-shot timeouts, not an interval: the gaps are deliberately
  // uneven and an interval would quantise them back onto a grid.
  timer = setTimeout(() => step(0), active.schedule[0]?.atMs ?? 0);
}

export function stopReplay(): void {
  clearTimer();
  active = null;
  emit(IDLE);
}

/** Test seam: forget all subscribers and state between cases. */
export function __resetReplayForTests(): void {
  clearTimer();
  active = null;
  listeners = new Set();
  state = IDLE;
}
