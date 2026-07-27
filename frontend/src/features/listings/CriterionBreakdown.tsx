// Criterion breakdown (P1-11, §9.3): renders the persisted scores.breakdown
// directly — no client-side re-derivation. When a gate fired, criteria is
// empty by contract and the UI says so instead of showing a hollow list.
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

import type { ScoreBreakdown } from "../../lib/contracts";
import { displayValue as formatCriterionValue } from "./displayValue";
import { useListingDetailDraft } from "./ListingDetailDraft";
import { OverrideControl } from "./OverrideControl";
import { activeOverrides, extractionForFloorPlan, REVERT_NOTE } from "./overrides";
import { scoreBand, scoreColor, formatScore } from "./scoreBands";
import classes from "./CriterionBreakdown.module.css";
import drawer from "./ListingDetailDrawer.module.css";
import type { Extraction, Override } from "./types";
import type { CatalogEntry } from "../rubric/api";

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
}: {
  extraction: Extraction;
  overridden: boolean;
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
          <EvidenceContent extraction={extraction} overridden={overridden} />
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
        <EvidenceContent extraction={extraction} overridden={overridden} />
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
}

export function CriterionBreakdown({
  breakdown,
  catalog,
  extractions,
  overrides,
  floorPlanId,
  isMobile,
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

  if (breakdown.gates.length > 0) {
    return (
      <Alert color={"danger"} title="A gate fired — criteria were not scored">
        <Stack gap="xs">
          {breakdown.gates.map((gate) => (
            <Text size="sm" key={gate.key}>
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
        </Text>
      </Group>
    </Box>
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
  isPending: boolean;
  isMobile: boolean;
  floorPlanId: string | null;
  onRevert: () => void;
}) {
  const showOverrideDot = savedOverride && !isPending;
  const valueOverridden = savedOverride || isPending;
  const evidenceOverridden = savedOverride || isPending;
  const flag = rowFlag(criterion, extraction, isPending);

  return (
    <Box className={classes.crit}>
      <Group gap={6} wrap="nowrap" className={classes.nameCell}>
        {showOverrideDot && (
          <Tooltip label="Value overridden">
            <Box component="span" className={classes.dot} aria-label="overridden" />
          </Tooltip>
        )}
        <Text size="sm">{entry?.label ?? criterion.key}</Text>
        {flag && (
          <Text component="span" size="xs" c="dimmed" fw={500} className={classes.flag}>
            {flag}
          </Text>
        )}
        {extraction && (
          <EvidenceButton
            extraction={extraction}
            overridden={evidenceOverridden}
            isMobile={isMobile}
          />
        )}
      </Group>
      <Text
        size="sm"
        fw={600}
        className={valueOverridden ? classes.overridden : undefined}
        c={criterion.unknown && !isPending && !valueOverridden ? "dimmed" : undefined}
      >
        {formatCriterionValue(value, criterion.key)}
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
      <Group gap={4} wrap="nowrap" justify="flex-end">
        <OverrideControl
          criterionKey={criterion.key}
          schema={entry?.value_schema}
          currentValue={value}
          factScope={entry?.fact_scope}
          floorPlanId={floorPlanId}
        />
        {showOverrideDot && (
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
        )}
      </Group>
    </Box>
  );
}
