// Pure mapping from a Job's raw stage/plan/state onto the six friendly
// pipeline phases the Active-job card renders (JobCard → PipelineTrack). The
// ~12 internal stage names (DESIGN §2.1 INGEST_STAGES, plus the legacy §19
// six-stage list) collapse into human phases; manifest cursor (stage_index)
// disambiguates duplicate stage names (e.g. the second FETCH after DISCOVER).
// View-agnostic and unit-tested — JobCard/PipelineTrack only render the model.
import type { Job, JobState } from "./api";

export type PhaseKey = "prepare" | "fetch" | "read" | "verify" | "inspect" | "finalize";
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

export interface ManifestProgress {
  index: number;
  total: number;
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
  // Position in the plan manifest (0-based cursor); drives the stage token fraction.
  manifestProgress: ManifestProgress | null;
}

export const PHASE_ORDER: PhaseKey[] = ["prepare", "fetch", "read", "verify", "inspect", "finalize"];

const PHASE_LABEL: Record<PhaseKey, string> = {
  prepare: "Prepare",
  fetch: "Fetch",
  read: "Read",
  verify: "Verify",
  inspect: "Inspect",
  finalize: "Finalize",
};

// Gerund used to build both the running caption ("Reading the listing…") and
// the failed caption ("Stopped while reading the listing").
const PHASE_GERUND: Record<PhaseKey, string> = {
  prepare: "preparing",
  fetch: "fetching the page",
  read: "reading the listing",
  verify: "verifying details",
  inspect: "inspecting images",
  finalize: "finalizing",
};

const CROSSCHECK_GERUND = "cross-checking other sources";

// The internal stages of each phase, in run order (DESIGN §2.1 INGEST_STAGES).
// Drives both STAGE_PHASE below and the active phase's sub-steps.
const PHASE_STAGES: Record<PhaseKey, string[]> = {
  prepare: ["PLAN", "VALIDATE_URL"],
  fetch: ["FETCH", "VALIDATE"],
  read: ["EXTRACT", "DEDUPE", "DISCOVER"],
  verify: ["VERIFY", "RECONCILE"],
  inspect: ["IMAGE_FETCH", "IMAGE_CLASSIFY", "VISION"],
  finalize: ["ENRICH", "SCORE"],
};

// Each internal stage (uppercased) → its friendly phase. Legacy lowercase names
// resolve identically once uppercased.
const STAGE_PHASE: Record<string, PhaseKey> = Object.fromEntries(
  (Object.entries(PHASE_STAGES) as [PhaseKey, string[]][]).flatMap(([phase, stages]) =>
    stages.map((stage) => [stage, phase]),
  ),
);

// Fallback stage list for pre-P3 jobs whose RunState carries no plan manifest
// (DESIGN §19 PHASE0_STAGES). Maps onto all six phases, so an old job still
// shows a full track.
const LEGACY_STAGES = ["validate_url", "fetch", "validate", "extract", "verify", "score"];

type PassContext = "primary" | "crosscheck" | "default";

const ACTIVE_STATES: JobState[] = ["running", "waiting_user", "failed", "cancelled"];

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

function manifestCursor(job: Job): number {
  if (job.stage_index != null && job.stage_index >= 0) return job.stage_index;
  const stages = planStages(job);
  const name = job.current_stage?.toUpperCase();
  if (!name) return -1;
  return stages.findIndex((s) => s.toUpperCase() === name);
}

function reachedMaxPhaseIndex(stages: string[], cursor: number): number {
  if (cursor < 0) return -1;
  let maxIdx = -1;
  for (let i = 0; i <= cursor && i < stages.length; i++) {
    const phase = phaseOfStage(stages[i]);
    if (phase === null) continue;
    const idx = PHASE_ORDER.indexOf(phase);
    if (idx > maxIdx) maxIdx = idx;
  }
  return maxIdx;
}

function lastIndexOfStage(stages: string[], name: string): number {
  const upper = name.toUpperCase();
  for (let i = stages.length - 1; i >= 0; i--) {
    if (stages[i].toUpperCase() === upper) return i;
  }
  return -1;
}

function passContext(job: Job, cursor: number, stages: string[]): PassContext {
  const stage = job.current_stage?.toUpperCase();
  if (!stage || cursor < 0) return "default";
  const discoverIdx = lastIndexOfStage(stages, "DISCOVER");
  if (discoverIdx >= 0 && cursor > discoverIdx && (stage === "FETCH" || stage === "EXTRACT")) {
    return "crosscheck";
  }
  return "primary";
}

function activePhaseHasDuplicates(activeKey: PhaseKey, manifestStages: string[]): boolean {
  const phaseStages = PHASE_STAGES[activeKey];
  return phaseStages.some(
    (s) => manifestStages.filter((m) => m.toUpperCase() === s).length > 1,
  );
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

function gerundFor(activeKey: PhaseKey | null, context: PassContext): string | null {
  if (!activeKey) return null;
  if (context === "crosscheck") return CROSSCHECK_GERUND;
  return PHASE_GERUND[activeKey];
}

function captionFor(
  state: JobState,
  activeKey: PhaseKey | null,
  context: PassContext,
): string | null {
  if (state === "waiting_user") return "Waiting for you";
  if (state === "queued") return "Waiting to start";
  const gerund = gerundFor(activeKey, context);
  if (!gerund) return null;
  if (state === "failed") return `Stopped while ${gerund}`;
  if (state === "cancelled") return `Cancelled while ${gerund}`;
  if (state === "running") return `${capitalize(gerund)}…`;
  return null;
}

function manifestProgressFor(job: Job, cursor: number, stages: string[]): ManifestProgress | null {
  const planStagesRaw = (job.plan as { stages?: unknown } | null | undefined)?.stages;
  if (!Array.isArray(planStagesRaw) || planStagesRaw.length === 0) return null;
  const total = stages.length;
  if (cursor < 0 || cursor >= total || total <= 1) return null;
  return { index: cursor, total };
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
  const stages = planStages(job);
  const cursor = manifestCursor(job);
  const context = passContext(job, cursor, stages);

  const present = new Set<PhaseKey>();
  for (const stage of stages) {
    const key = phaseOfStage(stage);
    if (key) present.add(key);
  }

  const currentPhase = phaseOfStage(job.current_stage);
  if (currentPhase) present.add(currentPhase);

  const currentIdx = currentPhase ? PHASE_ORDER.indexOf(currentPhase) : -1;
  const reachedMaxIdx = reachedMaxPhaseIndex(stages, cursor);

  const tone = toneFor(job.state);
  const isActive = ACTIVE_STATES.includes(job.state);
  const activeKey = isActive ? currentPhase : null;

  const phases: PhaseStatus[] = PHASE_ORDER.map((key, i) => {
    const label = PHASE_LABEL[key];
    if (job.state === "done") {
      return { key, label, status: present.has(key) ? "done" : "skipped", tone: null };
    }
    if (!present.has(key)) return { key, label, status: "skipped", tone: null };
    if (isActive && i === currentIdx) {
      return { key, label, status: "active", tone };
    }
    if (reachedMaxIdx >= 0 && i <= reachedMaxIdx) {
      return { key, label, status: "done", tone: null };
    }
    return { key, label, status: "pending", tone: null };
  });

  const substeps =
    activeKey && activePhaseHasDuplicates(activeKey, stages)
      ? null
      : subStepsFor(job, activeKey);

  return {
    phases,
    caption: captionFor(job.state, activeKey, context),
    stageToken: job.current_stage ? job.current_stage.toUpperCase() : null,
    substeps,
    manifestProgress: manifestProgressFor(job, cursor, stages),
  };
}
