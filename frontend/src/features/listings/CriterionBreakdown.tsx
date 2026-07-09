// Criterion breakdown (P1-11, §9.3): renders the persisted scores.breakdown
// directly — no client-side re-derivation. When a gate fired, criteria is
// empty by contract and the UI says so instead of showing a hollow list.
// Evidence and provenance are one tap away (HoverCard), not inline (§9.6).
import { Alert, Badge, Group, HoverCard, Stack, Table, Text } from "@mantine/core";

import type { ScoreBreakdown } from "../../lib/contracts";
import { semantic } from "../../theme";
import { displayValue } from "./displayValue";
import { OverrideControl } from "./OverrideControl";
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

export interface CriterionBreakdownProps {
  huntId: string;
  listingId: string;
  breakdown: ScoreBreakdown;
  catalog: CatalogEntry[];
  /** latest extraction per criterion key */
  extractions: Map<string, Extraction>;
  overrides: Override[];
}

export function CriterionBreakdown({
  huntId,
  listingId,
  breakdown,
  catalog,
  extractions,
  overrides,
}: CriterionBreakdownProps) {
  const catalogByKey = new Map(catalog.map((entry) => [entry.key, entry]));
  const overriddenKeys = new Set(overrides.map((o) => o.criterion_key));

  if (breakdown.gates.length > 0) {
    // §9.3: total is the minimum set-score and the delta pass never ran.
    return (
      <Alert color={semantic.danger} title="A gate fired — criteria were not scored">
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
      <Table.Tbody>
        {breakdown.criteria.map((criterion) => {
          const entry = catalogByKey.get(criterion.key);
          const extraction = extractions.get(criterion.key);
          const overridden = overriddenKeys.has(criterion.key);
          return (
            <Table.Tr key={criterion.key}>
              <Table.Td>
                <Text size="sm">{entry?.label ?? criterion.key}</Text>
              </Table.Td>
              <Table.Td>
                <HoverCard width={300} shadow="md" disabled={!extraction} position="top">
                  <HoverCard.Target>
                    <Group gap="xs" wrap="nowrap">
                      <Text size="sm" fw={600} c={criterion.unknown ? "dimmed" : undefined}>
                        {displayValue(criterion.value)}
                      </Text>
                      {overridden && (
                        <Badge size="xs" color={semantic.manual} variant="light">
                          override
                        </Badge>
                      )}
                    </Group>
                  </HoverCard.Target>
                  <HoverCard.Dropdown>
                    <Stack gap={4}>
                      {overridden && (
                        <Text size="xs">
                          Original: <Text span fw={600}>{displayValue(extraction?.value)}</Text>
                        </Text>
                      )}
                      {extraction?.evidence_quote && (
                        <Text size="xs" fs="italic">
                          “{extraction.evidence_quote}”
                        </Text>
                      )}
                      <Text size="xs" c="dimmed">
                        {extraction?.model} · {extraction?.confidence} confidence
                        {extraction?.extracted_at
                          ? ` · ${new Date(extraction.extracted_at).toLocaleDateString()}`
                          : ""}
                      </Text>
                    </Stack>
                  </HoverCard.Dropdown>
                </HoverCard>
              </Table.Td>
              <Table.Td width={70}>{deltaBadge(criterion.delta)}</Table.Td>
              <Table.Td width={40}>
                <OverrideControl
                  huntId={huntId}
                  listingId={listingId}
                  criterionKey={criterion.key}
                  schema={entry?.value_schema}
                  currentValue={criterion.value}
                />
              </Table.Td>
            </Table.Tr>
          );
        })}
      </Table.Tbody>
    </Table>
  );
}
