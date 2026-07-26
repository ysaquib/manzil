// Interest status → colour and label for the Overview (UI Decision Log 2026-07-26).
//
// Ten statuses is a lifecycle, not a flag, so the hue says where a row sits in
// it rather than merely that it has one: in the running, waiting on them,
// waiting on you, settled well, settled badly, out of play.
//
// Two scales are deliberately absent — grape (human-entered values) and dusty
// brick's neighbours are reserved so a chip can never be confused with an
// override dot or a danger state (UI_DESIGN §4). Colour is returned as a
// Mantine palette *name*, never a hex (UI_DESIGN §2).
import { sentenceCase } from "../../lib/text";
import type { InterestStatus } from "./types";

const TONE: Record<InterestStatus, string> = {
  interested: "cyan", // fog blue — in the running
  applied: "indigo", // storm — waiting on them
  offer_received: "yellow", // muted ochre — waiting on you
  offer_accepted: "green", // sage — settled, positive
  application_rejected: "red", // dusty brick — settled, negative
  offer_rescinded: "red",
  application_withdrawn: "gray", // warm stone — out of play
  offer_declined: "gray",
  not_interested: "gray",
  unavailable: "gray",
};

/** Mantine colour name for an interest status; warm neutral when undecided. */
export function interestTone(status: InterestStatus | null): string {
  if (status === null) return "gray";
  return TONE[status] ?? "gray";
}

// Title Case, matching the filter chips so the same vocabulary reads
// identically wherever it appears.
const LABEL: Partial<Record<InterestStatus, string>> = {
  application_rejected: "Rejected",
  application_withdrawn: "Withdrawn",
  offer_rescinded: "Rescinded",
};

export function interestLabel(status: InterestStatus | null): string {
  if (status === null) return "Undecided";
  const label = LABEL[status] ?? sentenceCase(status);
  return label.replace(/\b[a-z]/g, (c) => c.toUpperCase());
}
