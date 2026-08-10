// How many recorded ingests a demo visit still has left (DM-9, DESIGN §3, §16).
//
// A demo session ships a **slate** of Replay Captures rather than one. Each
// "submission" plays the next one in order; when the slate is exhausted,
// submitting is disabled until the visitor reloads.
//
// The cursor lives in module memory, not sessionStorage, and that is the whole
// point. `resetDemo()` is a reload, and DESIGN §16's promise is that a reload
// puts everything back — so the allowance has to be reload-scoped too, or the
// visitor could exhaust the demo and find no way back to it short of closing
// the tab. Module state gives that for free: nothing to clear, nothing to
// expire, nothing that can disagree with the query cache it moves in step with.
//
// **Not a security control**, for the same reason nothing else in `demo/` is.
// It is a budget on an animation that costs nothing and touches no network; the
// thing that actually keeps a demo session from spending money is the database
// refusing its writes. Anyone can reset this from devtools and gain nothing.

let used = 0;
let listeners = new Set<() => void>();

/** Runs consumed so far this page load. */
let snapshot = { used: 0 };

function emit() {
  // A fresh object per change, because `useSyncExternalStore` compares by
  // identity — and a stable one while nothing changes, because it also calls
  // the getter on every render and an object literal there would loop.
  snapshot = { used };
  listeners.forEach((listener) => listener());
}

export function subscribeToDemoSlate(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function demoSlateSnapshot(): { used: number } {
  return snapshot;
}

/**
 * Claim the next run.
 *
 * Returns the index into the slate to play, or null when `total` runs have
 * already been claimed. The caller passes the slate size rather than this
 * module knowing it: the captures load asynchronously and a counter that had to
 * wait for them would be a second source of truth for "is the demo ready".
 */
export function claimDemoRun(total: number): number | null {
  if (used >= total) return null;
  const index = used;
  used += 1;
  emit();
  return index;
}

/** Test seam: forget the cursor and every subscriber between cases. */
export function __resetDemoSlateForTests(): void {
  used = 0;
  snapshot = { used: 0 };
  listeners = new Set();
}
