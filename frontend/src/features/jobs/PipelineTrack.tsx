// Presentational pipeline track: renders the five-phase model from
// pipelinePhases as a horizontal dotted line with the current phase highlighted,
// its internal stages as sub-pips, a friendly caption, and the exact stage
// token. On History cards it is expandable — the whole region toggles an inline
// timeline (passed as children). All mapping logic lives in pipelinePhases.ts.
import { Text } from "@mantine/core";
import { IconChevronDown } from "@tabler/icons-react";
import type { KeyboardEvent, ReactNode } from "react";

import classes from "./PipelineTrack.module.css";
import type { PhaseStatus, PhaseTone, PipelineModel } from "./pipelinePhases";

function connectorFill(previous: PhaseStatus | undefined): string {
  if (!previous) return "none";
  if (previous.status === "done") return "done";
  if (previous.status === "active" && previous.tone === "running") return "shimmer";
  if (previous.status === "active" && previous.tone === "failed") return "failed";
  return "pending";
}

// Sub-pips + a caption fraction are only shown while the phase is actively being
// worked (running/waiting) — not for a stopped (failed/cancelled) phase.
function isLiveTone(tone: PhaseTone | null): tone is "running" | "waiting" {
  return tone === "running" || tone === "waiting";
}

function SubPips({ tone, total, index }: { tone: "running" | "waiting"; total: number; index: number }) {
  return (
    <span className={classes.substeps} data-tone={tone} aria-hidden>
      {Array.from({ length: total }, (_, i) => (
        <i key={i} className={classes.pip} data-s={i < index ? "done" : i === index ? "current" : "up"} />
      ))}
    </span>
  );
}

export function PipelineTrack({
  model,
  attempts = 0,
  trailing,
  expandable = false,
  expanded = false,
  onToggle,
  children,
}: {
  model: PipelineModel;
  attempts?: number;
  trailing?: ReactNode;
  expandable?: boolean;
  expanded?: boolean;
  onToggle?: () => void;
  children?: ReactNode;
}) {
  const active = model.phases.find((phase) => phase.status === "active");
  const activeTone = active?.tone ?? null;
  const live = isLiveTone(activeTone);
  const showSub = live && model.substeps !== null && model.substeps.total > 1;

  const tokenText =
    model.stageToken === null
      ? null
      : showSub && model.substeps
        ? `${model.stageToken} · ${model.substeps.index + 1}/${model.substeps.total}`
        : model.stageToken;

  const region = (
    <>
      <div className={classes.track}>
        {model.phases.map((phase, i) => (
          <div key={phase.key} className={classes.cell}>
            <span className={classes.connector} data-fill={connectorFill(model.phases[i - 1])} aria-hidden />
            <span
              className={classes.dot}
              data-status={phase.status}
              data-tone={phase.tone ?? undefined}
              title={`${phase.label} — ${phase.status}`}
            />
            <span className={classes.label} data-status={phase.status} data-tone={phase.tone ?? undefined}>
              {phase.label}
            </span>
            {phase.status === "active" && showSub && live && model.substeps && (
              <SubPips tone={activeTone} total={model.substeps.total} index={model.substeps.index} />
            )}
          </div>
        ))}
      </div>

      <div className={classes.capRow}>
        <div className={classes.caption}>
          {model.caption && (
            <span className={classes.captionText} data-tone={activeTone ?? undefined}>
              {model.caption}
            </span>
          )}
          {tokenText && <span className={classes.token}>{tokenText}</span>}
          {attempts > 1 && (
            <Text size="xs" c="dimmed" span>
              · attempt {attempts}
            </Text>
          )}
        </div>
        {expandable ? (
          <span className={classes.toggle}>
            Timeline
            <IconChevronDown size={12} className={classes.chevron} data-expanded={expanded} />
          </span>
        ) : (
          trailing && <div className={classes.trailing}>{trailing}</div>
        )}
      </div>
    </>
  );

  if (!expandable) {
    return (
      <div>
        {region}
        {expanded && children}
      </div>
    );
  }

  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onToggle?.();
    }
  };

  return (
    <div>
      <div
        className={classes.expandable}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        aria-label={`${model.caption ?? "Pipeline"} — ${expanded ? "hide" : "show"} timeline`}
        onClick={onToggle}
        onKeyDown={handleKey}
      >
        {region}
      </div>
      {expanded && children}
    </div>
  );
}
