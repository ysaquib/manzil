// Read-only rubric criterion card (§13.2 view mode): title, badges, and an
// options table with match label left and points right.
// Points are colored text, not badges — keeps the table quiet (DESIGN §20 2026-07-10).
import { Badge, Card, Group, Stack, Table, Text, Tooltip } from "@mantine/core";
import { IconShieldCheck, IconSparkles } from "@tabler/icons-react";
import type { ReactNode } from "react";

import type { RubricOption } from "../../lib/contracts";
import type { CatalogEntry, RubricCriterion } from "./api";
import { formatMatchLabel } from "./matchLabels";
import { deriveIsBonus } from "./rubricDraft";

function deltaColor(delta: number): string {
  if (delta > 0) return "green";
  if (delta < 0) return "red";
  return "dimmed";
}

function DeltaText({ delta }: { delta: number }) {
  const sign = delta > 0 ? "+" : "";
  return (
    <Text size="sm" fw={500} c={deltaColor(delta)} span>
      {sign}
      {delta}
    </Text>
  );
}

function OptionValue({ option }: { option: RubricOption }) {
  if (option.dealbreaker_set_score !== null) {
    return (
      <Text size="sm" c={"red"} fw={500}>
        sets score to {option.dealbreaker_set_score}
      </Text>
    );
  }
  return <DeltaText delta={option.delta} />;
}

function ValueCell({ children }: { children: ReactNode }) {
  return (
    <Table.Td ta="right" w={120}>
      {children}
    </Table.Td>
  );
}

export function CriterionViewCard({
  criterion,
  entry,
}: {
  criterion: RubricCriterion;
  entry: CatalogEntry;
}) {
  const isBonus = deriveIsBonus(criterion.options, criterion.unknown_delta);

  return (
    <Card h="100%">
      <Stack gap="sm">
        <Group gap="xs" wrap="wrap">
          <Text fw={600} size="sm">
            {entry.label}
          </Text>
          {isBonus && (
            <Tooltip label="Bonus criterion — all deltas are non-negative">
              <Badge
                size="xs"
                variant="light"
                color="green"
                leftSection={<IconSparkles size={12} stroke={1.5} />}
              >
                bonus
              </Badge>
            </Tooltip>
          )}
          {criterion.non_negotiable !== null && (
            <Tooltip label="Non-negotiable gate">
              <Badge
                size="xs"
                variant="light"
                color={"red"}
                leftSection={<IconShieldCheck size={12} stroke={1.5} />}
              >
                non-negotiable
              </Badge>
            </Tooltip>
          )}
        </Group>

        <Table verticalSpacing="xs" withRowBorders={false}>
          <Table.Tbody>
            {criterion.options.map((option, index) => (
              <Table.Tr key={index}>
                <Table.Td>
                  <Text size="sm">{formatMatchLabel(option.match, entry.value_schema)}</Text>
                </Table.Td>
                <ValueCell>
                  <OptionValue option={option} />
                </ValueCell>
              </Table.Tr>
            ))}
            {criterion.unknown_delta !== 0 && (
              <Table.Tr>
                <Table.Td>
                  <Text size="sm" c="dimmed">
                    If unknown
                  </Text>
                </Table.Td>
                <ValueCell>
                  <DeltaText delta={criterion.unknown_delta} />
                </ValueCell>
              </Table.Tr>
            )}
            {criterion.non_negotiable !== null && (
              <Table.Tr>
                <Table.Td>
                  <Text size="sm" c="dimmed">
                    If not met
                  </Text>
                </Table.Td>
                <ValueCell>
                  <Text size="sm" c={"red"} fw={500}>
                    score set to {criterion.non_negotiable.set_score}
                  </Text>
                </ValueCell>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Stack>
    </Card>
  );
}
