// Criterion breakdown (P1-11, §9.3): renders the persisted scores.breakdown
// directly — no client-side re-derivation. When a gate fired, criteria is
// empty by contract and the UI says so instead of showing a hollow list.
// Evidence and provenance sit behind an info affordance (HoverCard/Popover).
import {
  ActionIcon,
  Alert,
  Badge,
  Group,
  HoverCard,
  Popover,
  Stack,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconArrowBackUp, IconInfoCircle } from "@tabler/icons-react";
import { useState } from "react";

import type { ScoreBreakdown } from "../../lib/contracts";
import { displayValue as formatCriterionValue } from "./displayValue";
import { useListingDetailDraft } from "./ListingDetailDraft";
import { OverrideControl } from "./OverrideControl";
import { activeOverrides, REVERT_NOTE } from "./overrides";
import type { Extraction, Override } from "./types";
import type { CatalogEntry } from "../rubric/api";

function deltaBadge(delta: number) {
  const color = delta > 0 ? "green" : delta < 0 ? "red" : "gray";
  const sign = delta > 0 ? "+" : "";
  return (
    <Badge color={color} variant="light" size="sm">
      {sign}
      {delta}
    </Badge>
  );
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
  const icon = (
    <ActionIcon color="gray" size="sm" variant="subtle" aria-label="evidence">
      <IconInfoCircle size={14} stroke={1.5} color="var(--mantine-color-dimmed)" />
    </ActionIcon>
  );

  if (isMobile) {
    return (
      <Popover opened={opened} onChange={setOpened} width={300} position="top" withArrow shadow="md">
        <Popover.Target>
          <span onClick={() => setOpened((o) => !o)}>{icon}</span>
        </Popover.Target>
        <Popover.Dropdown>
          <EvidenceContent extraction={extraction} overridden={overridden} />
        </Popover.Dropdown>
      </Popover>
    );
  }

  return (
    <HoverCard width={300} shadow="md" position="top">
      <HoverCard.Target>{icon}</HoverCard.Target>
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
  /** latest extraction per criterion key */
  extractions: Map<string, Extraction>;
  overrides: Override[];
  isMobile: boolean;
}

export function CriterionBreakdown({
  breakdown,
  catalog,
  extractions,
  overrides,
  isMobile,
}: CriterionBreakdownProps) {
  const catalogByKey = new Map(catalog.map((entry) => [entry.key, entry]));
  // Latest-per-key, null tombstones excluded (§9.6) — a reverted criterion no
  // longer reads as overridden.
  const overriddenKeys = new Set(activeOverrides(overrides).keys());
  const { draftOverrides, setDraftOverride } = useListingDetailDraft();

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
    <Table verticalSpacing="xs" withRowBorders={false}>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>
            <Text size="xs" c="dimmed" fw={500}>
              Criterion
            </Text>
          </Table.Th>
          <Table.Th>
            <Text size="xs" c="dimmed" fw={500}>
              Value
            </Text>
          </Table.Th>
          <Table.Th>
            <Text size="xs" c="dimmed" fw={500}>
              Points
            </Text>
          </Table.Th>
          <Table.Th aria-label="override actions" />
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {breakdown.criteria.map((criterion) => {
          const entry = catalogByKey.get(criterion.key);
          const extraction = extractions.get(criterion.key);
          const savedOverride = overriddenKeys.has(criterion.key);
          const draftOverride = draftOverrides.get(criterion.key);
          const isPending = draftOverride !== undefined;
          const displayVal = isPending ? draftOverride.value : criterion.value;
          return (
            <CriterionRow
              key={criterion.key}
              criterion={criterion}
              entry={entry}
              extraction={extraction}
              displayValue={displayVal}
              savedOverride={savedOverride}
              isPending={isPending}
              isMobile={isMobile}
              onRevert={() =>
                setDraftOverride(criterion.key, { value: null, note: REVERT_NOTE })
              }
            />
          );
        })}
      </Table.Tbody>
    </Table>
  );
}

function CriterionRow({
  criterion,
  entry,
  extraction,
  displayValue: value,
  savedOverride,
  isPending,
  isMobile,
  onRevert,
}: {
  criterion: ScoreBreakdown["criteria"][number];
  entry: CatalogEntry | undefined;
  extraction: Extraction | undefined;
  displayValue: unknown;
  savedOverride: boolean;
  isPending: boolean;
  isMobile: boolean;
  onRevert: () => void;
}) {
  const showOverrideBadge = savedOverride && !isPending;
  const evidenceOverridden = savedOverride || isPending;

  return (
    <Table.Tr>
      <Table.Td>
        <Text size="sm">{entry?.label ?? criterion.key}</Text>
      </Table.Td>
      <Table.Td>
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" fw={600} c={criterion.unknown && !isPending ? "dimmed" : undefined}>
            {formatCriterionValue(value, criterion.key)}
          </Text>
          {isPending && (
            <Badge size="xs" color={"manual"} variant="light">
              pending
            </Badge>
          )}
          {showOverrideBadge && (
            <Badge size="xs" color={"manual"} variant="light">
              override
            </Badge>
          )}
          {/* location_safety is an override-first placeholder (DESIGN §20
              2026-07-18): no pipeline stage grades it, so an unknown here is
              expected, not missing data — say so instead of a bare dash. */}
          {criterion.key === "location_safety" && criterion.unknown && !isPending && (
            <Tooltip
              label="No automated safety source yet — grade it yourself (A+ to F) via override."
              multiline
              w={240}
            >
              <Badge size="xs" color="gray" variant="light">
                awaiting grade
              </Badge>
            </Tooltip>
          )}
        </Group>
      </Table.Td>
      <Table.Td width={70}>{deltaBadge(criterion.delta)}</Table.Td>
      <Table.Td width={72}>
        <Group gap={4} wrap="nowrap" justify="flex-end">
          {extraction && (
            <EvidenceButton
              extraction={extraction}
              overridden={evidenceOverridden}
              isMobile={isMobile}
            />
          )}
          <OverrideControl
            criterionKey={criterion.key}
            schema={entry?.value_schema}
            currentValue={value}
          />
          {showOverrideBadge && (
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
      </Table.Td>
    </Table.Tr>
  );
}
