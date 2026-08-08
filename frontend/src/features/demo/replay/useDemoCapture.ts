// Loading the Replay Capture bundle (DM-9).
//
// The bundle is produced by `manzil export-demo-capture` and committed at
// `./capture.json`. It is deliberately loaded through a glob rather than a
// static import for two reasons:
//
//   * **It may legitimately be absent.** A checkout that has never exported one
//     must still build. A fabricated placeholder is not an option — DESIGN §3 is
//     explicit that a Replay Capture is a recording, never a simulation, and a
//     committed stub would be exactly the simulation that rules out.
//   * **Real users should not download it.** It is a few hundred kilobytes of
//     pipeline output that only a demo visitor will ever animate, so it is
//     fetched lazily and only inside a demo session.

import { useEffect, useState } from "react";

import { isDemo } from "../../../lib/demo";
import type { Capture } from "./capture";

// Vite resolves this at build time: no file, no entry, no build error.
const bundles = import.meta.glob<Capture>("./capture.json", { import: "default" });

/** True when this build carries a Replay Capture at all. */
export function hasDemoCapture(): boolean {
  return Object.keys(bundles).length > 0;
}

/**
 * The bundled capture, or null.
 *
 * Null means either "not a demo session" or "this build has no recording", and
 * the caller must treat both the same way: do not offer a submission the demo
 * cannot honour.
 */
export function useDemoCapture(): Capture | null {
  const [capture, setCapture] = useState<Capture | null>(null);

  useEffect(() => {
    if (!isDemo()) return;
    const load = Object.values(bundles)[0];
    if (!load) return;
    let cancelled = false;
    void load().then((bundle) => {
      if (!cancelled) setCapture(bundle);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return capture;
}
