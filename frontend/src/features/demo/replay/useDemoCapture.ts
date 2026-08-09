// Loading the Replay Capture slate (DM-9).
//
// Bundles are produced by `manzil export-demo-capture` and committed beside
// this file as `capture.json`, `capture-2.json`, `capture-3.json`, and so on —
// a **slate** of recorded ingests, played one per demo submission in filename
// order. They are deliberately loaded through a glob rather than static imports
// for three reasons:
//
//   * **They may legitimately be absent.** A checkout that has never exported
//     one must still build, and a slate of two must not need a code change to
//     become a slate of five. A fabricated placeholder is not an option —
//     DESIGN §3 is explicit that a Replay Capture is a recording, never a
//     simulation, and a committed stub would be exactly the simulation that
//     rules out.
//   * **Real users should not download them.** Each is a few hundred kilobytes
//     of pipeline output that only a demo visitor will ever animate, so they are
//     fetched lazily and only inside a demo session.
//   * **Order must be stable.** Glob keys are sorted so run 2 is the same
//     recording on every machine and in every build.

import { useEffect, useState } from "react";

import { isDemo } from "../../../lib/demo";
import type { Capture } from "./capture";

// Vite resolves this at build time: no files, no entries, no build error. The
// pattern matches the exporter's default output (`capture.json`) and every
// numbered sibling, so adding a recording is a commit, not a code change.
const bundles = import.meta.glob<Capture>("./capture*.json", { import: "default" });

/** Loaders in filename order — the order the slate plays in. */
function ordered() {
  return Object.keys(bundles)
    .sort()
    .map((key) => bundles[key]);
}

/** How many recordings this build carries. */
export function demoCaptureCount(): number {
  return Object.keys(bundles).length;
}

/** True when this build carries a Replay Capture at all. */
export function hasDemoCapture(): boolean {
  return demoCaptureCount() > 0;
}

/**
 * The bundled slate, in play order.
 *
 * Empty means either "not a demo session" or "this build has no recordings",
 * and the caller must treat both the same way: do not offer a submission the
 * demo cannot honour.
 *
 * Every bundle is fetched up front rather than one per run. The slate is small,
 * a visitor who plays the first will very likely play the second, and loading
 * mid-click would put a network wait inside an animation whose whole claim is
 * that it makes no network calls.
 */
export function useDemoCaptures(): Capture[] {
  const [captures, setCaptures] = useState<Capture[]>([]);

  useEffect(() => {
    if (!isDemo()) return;
    const loaders = ordered();
    if (loaders.length === 0) return;
    let cancelled = false;
    void Promise.all(loaders.map((load) => load())).then((loaded) => {
      if (!cancelled) setCaptures(loaded);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return captures;
}
