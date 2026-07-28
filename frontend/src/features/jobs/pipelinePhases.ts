// Pure mapping from a Job's raw stage/plan/state onto the five friendly
// pipeline phases the Active-job card renders (JobCard → PipelineTrack). The
// ~12 internal stage names (DESIGN §2.1 INGEST_STAGES, plus the legacy §19
// six-stage list) collapse into human phases; this file is view-agnostic and
// unit-tested — JobCard/PipelineTrack only render the model it returns.
import type { Job, JobState } from "./api";

export type PhaseKey = "prepare" | "fetch" | "read" | "verify" | "score";
export type PhaseStatusKind = "done" | "active" | "pending" | "skipped";
export type PhaseTone = "running" | "waiting" | "failed" | "cancelled";

export interface PhaseStatus {
  key: PhaseKey;
  label: string;
  status: PhaseStatusKind;
  // Set only when status is "active"; drives the dot's accent color.
  tone: PhaseTone | null;
}

// Where the current stage sits inside its phase: `total` stages this job runs in
// the active phase, `index` of the current one (0-based). Drives the sub-pips.
export interface SubSteps {
  total: number;
  index: number;
}

export interface PipelineModel {
  phases: PhaseStatus[];
  // Friendly one-line status for the active/edge state, or null when the track
  // alone says enough (done).
  caption: string | null;
  // The exact current stage name, uppercased (e.g. "EXTRACT"), or null.
  stageToken: string | null;
  // Sub-steps of the active phase, or null when nothing is active.
  substeps: SubSteps | null;
}

export const PHASE_ORDER: PhaseKey[] = ["prepare", "fetch", "read", "verify", "score"];

const PHASE_LABEL: Record<PhaseKey, string> = {
  prepare: "Prepare",
  fetch: "Fetch",
  read: "Read",
  verify: "Verify",
  score: "Score",
};

// Gerund used to build both the running caption ("Reading the listing…") and
// the failed caption ("Stopped while reading the listing").
const PHASE_GERUND: Record<PhaseKey, string> = {
  prepare: "preparing",
  fetch: "fetching the page",
  read: "reading the listing",
  verify: "verifying details",
  score: "scoring",
};

// The internal stages of each phase, in run order (DESIGN §2.1 INGEST_STAGES).
// Drives both STAGE_PHASE below and the active phase's sub-steps.
const PHASE_STAGES: Record<PhaseKey, string[]> = {
  prepare: ["PLAN", "VALIDATE_URL"],
  fetch: ["FETCH", "VALIDATE"],
  read: ["EXTRACT", "DEDUPE", "DISCOVER"],
  verify: ["VERIFY", "RECONCILE", "IMAGE_FETCH", "IMAGE_CLASSIFY", "VISION", "ENRICH"],
  score: ["SCORE"],
};

// Each internal stage (uppercased) → its friendly phase. Legacy lowercase names
// resolve identically once uppercased.
const STAGE_PHASE: Record<string, PhaseKey> = Object.fromEntries(
  (Object.entries(PHASE_STAGES) as [PhaseKey, string[]][]).flatMap(([phase, stages]) =>
    stages.map((stage) => [stage, phase]),
  ),
);

// Fallback stage list for pre-P3 jobs whose RunState carries no plan manifest
// (DESIGN §19 PHASE0_STAGES). Maps onto all five phases, so an old job still
// shows a full track.
const LEGACY_STAGES = ["validate_url", "fetch", "validate", "extract", "verify", "score"];

function phaseOfStage(stage: string | null | undefined): PhaseKey | null {
  if (!stage) return null;
  return STAGE_PHASE[stage.toUpperCase()] ?? null;
}

function planStages(job: Job): string[] {
  const stages = (job.plan as { stages?: unknown } | null | undefined)?.stages;
  if (Array.isArray(stages) && stages.length > 0) {
    return stages.filter((s): s is string => typeof s === "string");
  }
  return LEGACY_STAGES;
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function toneFor(state: JobState): PhaseTone {
  if (state === "failed") return "failed";
  if (state === "cancelled") return "cancelled";
  if (state === "waiting_user") return "waiting";
  return "running";
}

function captionFor(state: JobState, activeKey: PhaseKey | null): string | null {
  if (state === "waiting_user") return "Waiting for you";
  if (state === "queued") return "Waiting to start";
  if (!activeKey) return null;
  if (state === "failed") return `Stopped while ${PHASE_GERUND[activeKey]}`;
  if (state === "cancelled") return `Cancelled while ${PHASE_GERUND[activeKey]}`;
  if (state === "running") return `${capitalize(PHASE_GERUND[activeKey])}…`;
  return null;
}

// The current stage's position within its phase, counting only the stages this
// job's plan actually runs. Null when there is no active phase.
function subStepsFor(job: Job, activeKey: PhaseKey | null): SubSteps | null {
  if (!activeKey || !job.current_stage) return null;
  const present = new Set(planStages(job).map((stage) => stage.toUpperCase()));
  const stages = PHASE_STAGES[activeKey].filter((stage) => present.has(stage));
  const total = stages.length;
  if (total === 0) return null;
  const found = stages.indexOf(job.current_stage.toUpperCase());
  return { total, index: found === -1 ? 0 : found };
}

export function phasesForJob(job: Job): PipelineModel {
  const present = new Set<PhaseKey>();
  for (const stage of planStages(job)) {
    const key = phaseOfStage(stage);
    if (key) present.add(key);
  }

  const currentPhase = phaseOfStage(job.current_stage);
  // A running/failed job's current phase is present even if the manifest is odd.
  if (currentPhase) present.add(currentPhase);
  const currentIdx = currentPhase ? PHASE_ORDER.indexOf(currentPhase) : -1;

  const tone = toneFor(job.state);
  // The current phase reads "active" while the job is live, failed, or cancelled
  // (so you can see where it stopped); once done or queued, nothing is active.
  const activeStates: JobState[] = ["running", "waiting_user", "failed", "cancelled"];
  const activeKey = activeStates.includes(job.state) ? currentPhase : null;

  const phases: PhaseStatus[] = PHASE_ORDER.map((key, i) => {
    const label = PHASE_LABEL[key];
    if (job.state === "done") {
      return { key, label, status: present.has(key) ? "done" : "skipped", tone: null };
    }
    if (!present.has(key)) return { key, label, status: "skipped", tone: null };
    if (currentIdx === -1) return { key, label, status: "pending", tone: null };
    if (i < currentIdx) return { key, label, status: "done", tone: null };
    if (i === currentIdx && activeKey === key) {
      return { key, label, status: "active", tone };
    }
    return { key, label, status: "pending", tone: null };
  });

  return {
    phases,
    caption: captionFor(job.state, activeKey),
    stageToken: job.current_stage ? job.current_stage.toUpperCase() : null,
    substeps: subStepsFor(job, activeKey),
  };
}
