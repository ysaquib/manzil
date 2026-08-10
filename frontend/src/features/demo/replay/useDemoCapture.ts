// Protected, release-backed Replay Capture loading (DESIGN §20 v3.72).
// Captures are no longer world-readable build artifacts. The current ordinal
// is fetched lazily with the Demo token and only after the release manifest is
// known.

export { useDemoCapture, useDemoRelease } from "../api";
