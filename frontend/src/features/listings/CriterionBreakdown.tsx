// Criterion breakdown (P1-11, §9.3): renders the persisted scores.breakdown
// directly — no client-side re-derivation. When a gate fired, an alert names
// the gate-pass matched option and the criteria rows below are informational.
// Evidence and provenance sit behind an info affordance (HoverCard/Popover).
import {
  ActionIcon,
  Alert,
  Box,
  Group,
  HoverCard,
  Popover,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconArrowBackUp, IconInfoCircle } from "@tabler/icons-react";
import { Fragment, useState } from "react";

import type { GateFiring, OptionMatch, ScoreBreakdown } from "../../lib/contracts";
import { formatMatchLabel } from "../rubric/matchLabels";
import { displayValue as formatCriterionValue } from "./displayValue";
import { useListingDetailDraft } from "./ListingDetailDraft";
import { useResolutionCandidates } from "./api";
import { OverrideControl } from "./OverrideControl";
import { activeOverrides, extractionForFloorPlan, REVERT_NOTE } from "./overrides";
import { scoreBand, scoreColor, formatScore } from "./scoreBands";
import classes from "./CriterionBreakdown.module.css";
import drawer from "./ListingDetailDrawer.module.css";
import type { Extraction, Override, ResolutionCandidate } from "./types";
import type { CatalogEntry } from "../rubric/api";
import { memberDisplayName } from "../collaboration/memberDisplay";
import type { HuntContributor, HuntMember } from "../collaboration/api";

function isAdvertisedUnconfirmed(value: unknown): boolean {
  if (value === "advertised_unconfirmed") return true;
  return (
    Array.isArray(value) &&
    value.some((item) => item === "advertised_unconfirmed")
  );
}

function gateHasLegacyShape(gate: GateFiring): boolean {
  return gate.value === undefined && gate.matched === undefined;
}

function resolveGateFields(
  gate: GateFiring,
  criteriaRow: ScoreBreakdown["criteria"][number] | undefined,
): { value: unknown; matched: OptionMatch | null | undefined } {
  if (gateHasLegacyShape(gate)) {
    if (criteriaRow) {
      return { value: criteriaRow.value, matched: criteriaRow.matched };
    }
    return { value: undefined, matched: undefined };
  }
  return { value: gate.value, matched: gate.matched ?? null };
}

function formatGateLine(
  gate: GateFiring,
  label: string,
  criteriaRow: ScoreBreakdown["criteria"][number] | undefined,
): string {
  const { value, matched } = resolveGateFields(gate, criteriaRow);
  const setScore = gate.set_score;

  if (gate.kind === "dealbreaker") {
    if (matched) {
      return `${label}: "${formatMatchLabel(matched, gate.key)}" is a dealbreaker — score set to ${setScore}`;
    }
    if (value !== undefined && value !== null) {
      return `${label}: ${formatCriterionValue(value, gate.key)} is a dealbreaker — score set to ${setScore}`;
    }
    return `${label} matched a dealbreaker — score set to ${setScore}`;
  }

  if (value === undefined || value === null) {
    return `${label}: unknown — score set to ${setScore}`;
  }
  if (isAdvertisedUnconfirmed(value)) {
    return `${label}: advertised, unconfirmed (not gate-sufficient) — score set to ${setScore}`;
  }
  if (matched) {
    return `${label} matched "${formatMatchLabel(matched, gate.key)}" (not acceptable) — score set to ${setScore}`;
  }
  return `${label}: ${formatCriterionValue(value, gate.key)} matched no option — score set to ${setScore}`;
}

function applicabilityLabel(extraction: Extraction): string | null {
  if (extraction.target_scope === "floor_plan") return "this floor plan";
  if (extraction.applicability === "all_units") return "all units";
  if (extraction.applicability === "select_units") return "select units";
  if (extraction.applicability === "unit_scope_unspecified") return "units unspecified";
  return null;
}

function EvidenceContent({
  extraction,
  overridden,
  candidates,
}: {
  extraction: Extraction;
  overridden: boolean;
  candidates: ResolutionCandidate[];
}) {
  return (
    <Stack gap={4}>
      {overridden && (
        <Text size="xs">
          Original:{" "}
          <Text span fw={600}>
            {formatCriterionValue(extraction.value, extraction.criterion_key)}
          </Text>
        </Text>
      )}
      {extraction.evidence_quote && (
        <Text size="xs" fs="italic">
          “{extraction.evidence_quote}”
        </Text>
      )}
      {/* management_reviews carries a synthesized summary alongside the rating
          (P3-8 ratings stage 1) — show it where provenance already lives. */}
      {typeof extraction.value === "object" &&
        extraction.value !== null &&
        typeof (extraction.value as { summary?: unknown }).summary === "string" && (
          <Text size="xs">{(extraction.value as { summary: string }).summary}</Text>
        )}
      <Text size="xs" c="dimmed">
        {extraction.model} · {extraction.confidence} confidence
        {extraction.extracted_at
          ? ` · ${new Date(extraction.extracted_at).toLocaleDateString()}`
          : ""}
      </Text>
      {extraction.resolution_rule && (
        <Text size="xs" c="dimmed">
          Resolution: {extraction.resolution_rule.replaceAll("_", " ")}
        </Text>
      )}
      {candidates.length > 1 && (
        <Stack gap={2} mt={2}>
          <Text size="xs" fw={600}>
            Source candidates
          </Text>
          {candidates.map((candidate) => (
            <Text key={candidate.id} size="xs" c={candidate.selected ? undefined : "dimmed"}>
              {candidate.selected ? "Selected: " : ""}
              {formatCriterionValue(candidate.value, extraction.criterion_key)}
              {candidate.source ? ` · ${candidate.source.site_domain}` : ""}
              {` · ${candidate.confidence}`}
            </Text>
          ))}
        </Stack>
      )}
    </Stack>
  );
}

function EvidenceButton({
  extraction,
  overridden,
  isMobile,
}: {
  extraction: Extraction;
  overridden: boolean;
  isMobile: boolean;
}) {
  const [opened, setOpened] = useState(false);
  const multiSource =
    extraction.resolution_rule !== null &&
    extraction.resolution_rule !== "single_source" &&
    !extraction.resolution_rule.startsWith("vision_");
  const { data: candidates = [] } = useResolutionCandidates(extraction.id, multiSource);

  if (isMobile) {
    return (
      <Popover opened={opened} onChange={setOpened} width={300} position="top" withArrow shadow="md">
        <Popover.Target>
          <ActionIcon
            color="gray"
            size="sm"
            variant="subtle"
            aria-label="evidence"
            onClick={() => setOpened((o) => !o)}
          >
            <IconInfoCircle size={14} stroke={1.5} color="var(--mantine-color-dimmed)" />
          </ActionIcon>
        </Popover.Target>
        <Popover.Dropdown>
          <EvidenceContent
            extraction={extraction}
            overridden={overridden}
            candidates={candidates}
          />
        </Popover.Dropdown>
      </Popover>
    );
  }

  return (
    <HoverCard width={300} shadow="md" position="top">
      <HoverCard.Target>
        <ActionIcon color="gray" size="sm" variant="subtle" aria-label="evidence">
          <IconInfoCircle size={14} stroke={1.5} color="var(--mantine-color-dimmed)" />
        </ActionIcon>
      </HoverCard.Target>
      <HoverCard.Dropdown>
        <EvidenceContent
          extraction={extraction}
          overridden={overridden}
          candidates={candidates}
        />
      </HoverCard.Dropdown>
    </HoverCard>
  );
}

export interface CriterionBreakdownProps {
  huntId: string;
  listingId: string;
  breakdown: ScoreBreakdown;
  catalog: CatalogEntry[];
  extractions: Extraction[];
  overrides: Override[];
  floorPlanId: string | null;
  isMobile: boolean;
  members?: (HuntMember | HuntContributor)[];
}

export function CriterionBreakdown({
  breakdown,
  catalog,
  extractions,
  overrides,
  floorPlanId,
  isMobile,
  members = [],
}: CriterionBreakdownProps) {
  const catalogByKey = new Map(catalog.map((entry) => [entry.key, entry]));
  // Latest-per-key, null tombstones excluded (§9.6) — a reverted criterion no
  // longer reads as overridden.
  const effectiveOverrides = activeOverrides(overrides, floorPlanId);
  const overriddenKeys = new Set(effectiveOverrides.keys());
  const { draftOverrides, setDraftOverride } = useListingDetailDraft();
  const displayedCriteria = [
    ...breakdown.criteria.filter(
      (criterion) => catalogByKey.get(criterion.key)?.fact_scope === "property",
    ),
    ...breakdown.criteria.filter(
      (criterion) => catalogByKey.get(criterion.key)?.fact_scope !== "property",
    ),
  ];

  const legacyGatedOnly =
    breakdown.gates.length > 0 &&
    breakdown.criteria.length === 0 &&
    breakdown.gates.every(gateHasLegacyShape);

  const gateCap =
    breakdown.gates.length > 0
      ? Math.min(...breakdown.gates.map((gate) => gate.set_score))
      : null;

  const criteriaByKey = new Map(breakdown.criteria.map((row) => [row.key, row]));

  if (legacyGatedOnly) {
    return (
      <Alert color={"danger"} title={`A gate fired — score capped at ${gateCap}`}>
        <Stack gap="xs">
          {breakdown.gates.map((gate) => (
            <Text size="sm" key={`${gate.key}:${gate.kind}`}>
              <Text span fw={600}>
                {catalogByKey.get(gate.key)?.label ?? gate.key}
              </Text>{" "}
              {gate.kind === "dealbreaker" ? "matched a dealbreaker" : "failed a non-negotiable"} —
              score set to {gate.set_score}.
            </Text>
          ))}
        </Stack>
      </Alert>
    );
  }

  return (
    <Stack gap="md">
      {breakdown.gates.length > 0 && (
        <Alert color={"danger"} title={`A gate fired — score capped at ${gateCap}`}>
          <Stack gap="xs">
            {breakdown.gates.map((gate) => (
              <Text size="sm" key={`${gate.key}:${gate.kind}`}>
                {formatGateLine(
                  gate,
                  catalogByKey.get(gate.key)?.label ?? gate.key,
                  criteriaByKey.get(gate.key),
                )}
              </Text>
            ))}
            <Text size="xs" c="dimmed">
              Criterion deltas below are informational; total reflects the gate cap.
            </Text>
          </Stack>
        </Alert>
      )}
      <Box className={classes.wrap}>
      <Group justify="space-between" align="baseline" className={classes.baseRow} wrap="nowrap">
        <Text size="xs" c="dimmed">
          Baseline{" "}
          <Text component="span" className={classes.baseNote}>
            — all your needs met
          </Text>
        </Text>
        <Text size="sm" fw={700} className={drawer.tabularNums}>
          {breakdown.base.toFixed(1)}
        </Text>
      </Group>
      {displayedCriteria.map((criterion, index) => {
        const entry = catalogByKey.get(criterion.key);
        const section = entry?.fact_scope === "property" ? "Property facts" : "Floor plan facts";
        const previous = index > 0 ? catalogByKey.get(displayedCriteria[index - 1].key) : undefined;
        const previousSection =
          previous?.fact_scope === "property" ? "Property facts" : "Floor plan facts";
        const extraction = extractionForFloorPlan(extractions, criterion.key, floorPlanId);
        const savedOverrideRow = effectiveOverrides.get(criterion.key);
        const savedOverride = overriddenKeys.has(criterion.key);
        const draftOverride = draftOverrides.get(criterion.key);
        const isPending = draftOverride !== undefined;
        const displayVal = isPending ? draftOverride.value : criterion.value;
        return (
          <Fragment key={criterion.key}>
            {(index === 0 || section !== previousSection) && (
              <Text className={classes.groupLabel} tt="uppercase" fw={700} c="dimmed">
                {section}
              </Text>
            )}
            <CriterionRow
              criterion={criterion}
              entry={entry}
              extraction={extraction}
              displayValue={displayVal}
              savedOverride={savedOverride}
              overrideBy={
                savedOverrideRow
                  ? memberDisplayName(members, savedOverrideRow.user_id)
                  : undefined
              }
              isPending={isPending}
              isMobile={isMobile}
              floorPlanId={floorPlanId}
              onRevert={() =>
                setDraftOverride(criterion.key, {
                  value: null,
                  note: REVERT_NOTE,
                  target_scope: savedOverrideRow?.target_scope ?? "property",
                  floor_plan_id: savedOverrideRow?.floor_plan_id ?? null,
                  applicability: savedOverrideRow?.applicability ?? null,
                })
              }
            />
          </Fragment>
        );
      })}
      <Text size="xs" c="dimmed" className={classes.legend}>
        Each criterion nudges the baseline · above 10 also meets your wants · capped 0–15.
      </Text>
      <Group justify="space-between" align="baseline" className={classes.totalRow} wrap="nowrap">
        <Text size="sm" fw={600}>
          Total score
        </Text>
        <Text
          component="span"
          className={`${classes.totalVal} ${drawer.bandText}`}
          data-band={scoreColor(breakdown.total).replace("score", "").toLowerCase()}
        >
          {formatScore(breakdown.total)}
          {scoreBand(breakdown.total) === 0 && (
            <Text component="span" className={drawer.drawerExcMark}>
              ✦
            </Text>
          )}
          <Text component="span" size="sm" c="dimmed" fw={400} className={classes.denom}>
            {" "}
            / 15
          </Text>
          {breakdown.gates.length > 0 && (
            <Text component="span" size="xs" c="dimmed" fw={400}>
              {" "}
              (gate cap)
            </Text>
          )}
        </Text>
      </Group>
      </Box>
    </Stack>
  );
}

// applicability / disputed / awaiting-grade collapse into one quiet text flag
// (no pill pile-up). Location safety has no automated grader, so an unknown is
// expected — say "awaiting grade" instead of surfacing scope/disagreement noise.
function rowFlag(
  criterion: ScoreBreakdown["criteria"][number],
  extraction: Extraction | undefined,
  isPending: boolean,
): string | null {
  if (criterion.key === "location_safety" && criterion.unknown && !isPending) {
    return "awaiting grade";
  }
  const parts: string[] = [];
  const applicability = extraction ? applicabilityLabel(extraction) : null;
  if (applicability) parts.push(applicability);
  if (extraction?.disputed) parts.push("sources disagree");
  return parts.length > 0 ? parts.join(" · ") : null;
}

function CriterionRow({
  criterion,
  entry,
  extraction,
  displayValue: value,
  savedOverride,
  overrideBy,
  isPending,
  isMobile,
  floorPlanId,
  onRevert,
}: {
  criterion: ScoreBreakdown["criteria"][number];
  entry: CatalogEntry | undefined;
  extraction: Extraction | undefined;
  displayValue: unknown;
  savedOverride: boolean;
  overrideBy?: string;
  isPending: boolean;
  isMobile: boolean;
  floorPlanId: string | null;
  onRevert: () => void;
}) {
  const showOverrideDot = savedOverride && !isPending;
  const valueOverridden = savedOverride || isPending;
  const evidenceOverridden = savedOverride || isPending;
  // An extracted Criterion reading unknown means the pipeline found nothing; a
  // manual one means nobody has answered it yet. Those are different problems
  // and must not render identically (§9.2).
  const needsAnswer =
    entry?.acquisition === "manual" && criterion.unknown && !isPending && !valueOverridden;
  const flag = rowFlag(criterion, extraction, isPending);
  const showRevert = showOverrideDot || isPending;
  const galleryEstimate = extraction?.resolution_rule === "vision_weighted_median_gallery";

  return (
    <Box
      className={classes.crit}
      data-hover-reveal={!showRevert ? "true" : undefined}
    >
      <Box className={classes.nameCell}>
        <Group gap={6} wrap="nowrap" className={classes.nameLine}>
          {showOverrideDot && (
            <Tooltip
              label={
                overrideBy ? `Overridden manually by ${overrideBy}` : "Value overridden manually"
              }
            >
              <Box component="span" className={classes.dot} aria-label="overridden" />
            </Tooltip>
          )}
          <Text size="sm">{entry?.label ?? criterion.key}</Text>
        </Group>
        {(galleryEstimate || flag || extraction) && (
          <Box className={classes.subline}>
            {galleryEstimate && (
              <Tooltip label="Property-gallery estimate — this kitchen may not represent this Floor Plan.">
                <Text component="span" inherit>
                  Property-gallery estimate
                </Text>
              </Tooltip>
            )}
            {flag && <Text component="span" inherit>{flag}</Text>}
            {extraction && (
              <EvidenceButton
                extraction={extraction}
                overridden={evidenceOverridden}
                isMobile={isMobile}
              />
            )}
          </Box>
        )}
      </Box>
      <Text
        size="sm"
        fw={600}
        className={valueOverridden ? classes.overridden : undefined}
        c={
          needsAnswer
            ? undefined
            : criterion.unknown && !isPending && !valueOverridden
              ? "dimmed"
              : undefined
        }
        fs={needsAnswer ? "italic" : undefined}
      >
        {needsAnswer ? "Needs your answer" : formatCriterionValue(value, criterion.key)}
      </Text>
      <Text
        size="sm"
        fw={700}
        ta="right"
        className={`${classes.delta} ${drawer.tabularNums} ${
          criterion.delta > 0 ? classes.pos : criterion.delta < 0 ? classes.neg : classes.zero
        }`}
      >
        {criterion.delta > 0 ? "+" : ""}
        {criterion.delta.toFixed(2)}
      </Text>
      <Group gap={4} wrap="nowrap" justify="flex-end" className={classes.rowAction}>
        {showRevert ? (
          <Tooltip label="Revert to original value">
            <ActionIcon
              color="gray"
              size="sm"
              variant="subtle"
              aria-label={`revert ${criterion.key} override`}
              onClick={onRevert}
            >
              <IconArrowBackUp size={14} stroke={1.5} color="var(--mantine-color-dimmed)" />
            </ActionIcon>
          </Tooltip>
        ) : (
          <OverrideControl
            criterionKey={criterion.key}
            schema={entry?.value_schema}
            currentValue={value}
            factScope={entry?.fact_scope}
            floorPlanId={floorPlanId}
            className={drawer.hoverRevealPencil}
          />
        )}
      </Group>
    </Box>
  );
}
