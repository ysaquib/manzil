// Read-only rubric criterion card (§13.2 view mode): a category-hued identity
// tile, the title, quiet state glyphs, and a points ledger.
//
// Ledger conventions (UI Decision Log 2026-07-25):
// - Points are mono tabular figures coloured by sign — not badges; a card can
//   carry six of them and badges would pile up (UI_DESIGN §4).
// - Each row carries a diverging bar scaled to the criterion's own largest
//   delta, so "which option actually moves the score" reads without arithmetic.
// - Dealbreaker rows have no bar: setting the final score isn't a delta, so the
//   row hands the bar and figure columns to its own text.
import { Box, Card, Group, Stack, Table, Text } from "@mantine/core";
import { IconHelpCircle, IconShieldCheck } from "@tabler/icons-react";
import type { ReactNode } from "react";

import type { RubricOption } from "../../lib/contracts";
import type { CatalogEntry, RubricCriterion } from "./api";
import { CriterionTile } from "./criterionIcon";
import { BonusMark, GateMark } from "./CriterionMarkers";
import { deltaFill, deltaScale } from "./deltaBar";
import { formatMatchLabel } from "./matchLabels";
import { deriveIsBonus, isOptionDealbreaker } from "./rubricDraft";
import classes from "./CriterionViewCard.module.css";

function deltaColor(delta: number): string {
  if (delta > 0) return "green";
  if (delta < 0) return "red";
  return "dimmed";
}

function signedDelta(delta: number): string {
  return delta > 0 ? `+${delta}` : String(delta);
}

/** Centre-out magnitude bar. Decorative — the figure beside it carries the value. */
function DeltaBar({ delta, scale }: { delta: number; scale: number }) {
  const fill = deltaFill(delta, scale);
  return (
    <Box className={classes.track} aria-hidden>
      {fill > 0 && (
        <Box
          className={classes.fill}
          data-sign={delta > 0 ? "pos" : "neg"}
          style={{ "--fill": fill } as React.CSSProperties}
        />
      )}
    </Box>
  );
}

/** One label → points row, with its bar. */
function DeltaRow({
  label,
  delta,
  scale,
  dimmed = false,
  icon,
}: {
  label: string;
  delta: number;
  scale: number;
  dimmed?: boolean;
  icon?: ReactNode;
}) {
  return (
    <Table.Tr>
      <Table.Td>
        <Group gap={6} wrap="nowrap">
          {icon}
          <Text size="sm" c={dimmed ? "dimmed" : undefined}>
            {label}
          </Text>
        </Group>
      </Table.Td>
      <Table.Td className={classes.barCell}>
        <DeltaBar delta={delta} scale={scale} />
      </Table.Td>
      <Table.Td className={classes.points}>
        <Text size="sm" fw={delta === 0 ? 400 : 500} c={deltaColor(delta)} span inherit>
          {signedDelta(delta)}
        </Text>
      </Table.Td>
    </Table.Tr>
  );
}

/** A row whose outcome is a set score, not a delta — no bar, text runs wide. */
function SetScoreRow({
  label,
  text,
  dimmed = false,
  icon,
}: {
  label: string;
  text: string;
  dimmed?: boolean;
  icon?: ReactNode;
}) {
  return (
    <Table.Tr>
      <Table.Td>
        <Group gap={6} wrap="nowrap">
          {icon}
          <Text size="sm" c={dimmed ? "dimmed" : undefined}>
            {label}
          </Text>
        </Group>
      </Table.Td>
      <Table.Td className={classes.points} colSpan={2}>
        <Text size="sm" fw={500} c="red" span inherit>
          {text}
        </Text>
      </Table.Td>
    </Table.Tr>
  );
}

const dimIcon = <IconHelpCircle size={14} stroke={1.5} color="var(--mantine-color-dimmed)" />;
const gateIcon = <IconShieldCheck size={14} stroke={1.5} color="var(--mantine-color-dimmed)" />;

function OptionRow({
  option,
  entry,
  scale,
}: {
  option: RubricOption;
  entry: CatalogEntry;
  scale: number;
}) {
  const label = formatMatchLabel(option.match, entry.key);
  if (isOptionDealbreaker(option)) {
    return <SetScoreRow label={label} text={`sets score to ${option.dealbreaker_set_score}`} />;
  }
  return <DeltaRow label={label} delta={option.delta} scale={scale} />;
}

export function CriterionViewCard({
  criterion,
  entry,
}: {
  criterion: RubricCriterion;
  entry: CatalogEntry;
}) {
  const isBonus = deriveIsBonus(criterion.options, criterion.unknown_delta);
  const scale = deltaScale(criterion.options, criterion.unknown_delta);
  const showUnknown = criterion.unknown_delta !== 0;
  const gate = criterion.non_negotiable;

  return (
    <Card>
      <Stack gap="sm">
        <Group gap="xs" wrap="nowrap">
          <CriterionTile entry={entry} />
          <Text fw={600} size="sm" truncate style={{ minWidth: 0 }}>
            {entry.label}
          </Text>
          {isBonus && <BonusMark />}
          {gate !== null && <GateMark setScore={gate.set_score} />}
        </Group>

        <Table
          verticalSpacing={4}
          horizontalSpacing="xs"
          withRowBorders={false}
          className={classes.ledger}
        >
          <Table.Tbody>
            {criterion.options.map((option, index) => (
              <OptionRow key={index} option={option} entry={entry} scale={scale} />
            ))}
          </Table.Tbody>

          {(showUnknown || gate !== null) && (
            <Table.Tbody className={classes.footer}>
              {showUnknown && (
                <DeltaRow
                  label="If unknown"
                  delta={criterion.unknown_delta}
                  scale={scale}
                  dimmed
                  icon={dimIcon}
                />
              )}
              {gate !== null && (
                <SetScoreRow
                  label="If not met"
                  text={`score → ${gate.set_score}`}
                  dimmed
                  icon={gateIcon}
                />
              )}
            </Table.Tbody>
          )}
        </Table>
      </Stack>
    </Card>
  );
}
