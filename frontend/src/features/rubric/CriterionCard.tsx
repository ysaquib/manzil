// One criterion's rubric editor (§13.2): aligned option grid (match | points |
// dealbreaker | remove), unknown-value row, non-negotiable gate. is_bonus is
// derived and display-only (§9.2).
//
// Layout decisions (UI polish pass, 2026-07-18):
// - Options are grid rows with fixed columns — inputs align down the card and
//   never wrap to a second line.
// - Dealbreaker is an ActionIcon toggle; when armed, the points input becomes
//   the red "sets score to" input in the same column (a dealbreaker's delta is
//   meaningless, so the swap loses nothing and saves a column).
// - Boolean criteria render fixed True/False rows as plain text — never a
//   switch; each row just gets its own points.
//
// Header (UI Decision Log 2026-07-25): enable switch, category-hued identity
// tile, label, the catalog's extraction hint, then quiet bonus/gate glyphs. The
// editor only renders criteria that are switched on — everything else lives in
// the group's CriterionPicker strip — so this card is always a scored one.
import {
  ActionIcon,
  Button,
  Card,
  Divider,
  Group,
  NumberInput,
  Stack,
  Switch,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconBan,
  IconHelpCircle,
  IconInfoCircle,
  IconPlus,
  IconTrash,
  IconX,
} from "@tabler/icons-react";

import type { RubricOption } from "../../lib/contracts";
import type { CatalogEntry, RubricCriterion } from "./api";
import { CriterionTile } from "./criterionIcon";
import { BonusMark, GateMark } from "./CriterionMarkers";
import { GateControls } from "./GateControls";
import { OptionMatchEditor } from "./OptionMatchEditor";
import { OptionGridRow } from "./OptionGridRow";
import { deriveIsBonus, isOptionDealbreaker } from "./rubricDraft";

function PointsInput({
  value,
  onChange,
  ariaLabel,
}: {
  value: number;
  onChange: (next: number) => void;
  ariaLabel: string;
}) {
  return (
    <NumberInput
      aria-label={ariaLabel}
      size="xs"
      step={0.25}
      prefix={value > 0 ? "+" : undefined}
      suffix=" pts"
      value={value}
      onChange={(next) => onChange(typeof next === "number" ? next : 0)}
    />
  );
}

function DealbreakerScoreInput({
  value,
  onChange,
}: {
  value: number;
  onChange: (next: number) => void;
}) {
  return (
    <Tooltip label="Matching this option sets the final score to this value" openDelay={300}>
      <NumberInput
        aria-label="dealbreaker set score"
        size="xs"
        min={0}
        max={15}
        prefix="→ "
        error
        value={value}
        onChange={(next) => onChange(typeof next === "number" ? next : 0)}
      />
    </Tooltip>
  );
}

function DealbreakerToggle({
  active,
  onToggle,
}: {
  active: boolean;
  onToggle: () => void;
}) {
  return (
    <Tooltip
      label={
        active
          ? "Dealbreaker — matching sets the score directly. Click to score points instead."
          : "Make this option a dealbreaker"
      }
      openDelay={300}
    >
      <ActionIcon
        size="sm"
        variant={active ? "filled" : "subtle"}
        color={active ? "red" : "gray"}
        aria-label="dealbreaker"
        aria-pressed={active}
        onClick={onToggle}
      >
        <IconBan size={14} stroke={1.5} />
      </ActionIcon>
    </Tooltip>
  );
}

function OptionRow({
  option,
  entry,
  onChange,
  onRemove,
}: {
  option: RubricOption;
  entry: CatalogEntry;
  onChange: (option: RubricOption) => void;
  onRemove: () => void;
}) {
  const isDealbreaker = isOptionDealbreaker(option);
  return (
    <OptionGridRow>
      <OptionMatchEditor
        match={option.match}
        schema={entry.value_schema}
        criterionKey={entry.key}
        onChange={(match) => onChange({ ...option, match })}
      />
      {isDealbreaker ? (
        <DealbreakerScoreInput
          value={option.dealbreaker_set_score ?? 0}
          onChange={(next) => onChange({ ...option, dealbreaker_set_score: next })}
        />
      ) : (
        <PointsInput
          ariaLabel="option delta"
          value={option.delta}
          onChange={(delta) => onChange({ ...option, delta })}
        />
      )}
      <Group gap={4} >
        <DealbreakerToggle
          active={isDealbreaker}
          onToggle={() =>
            onChange({ ...option, dealbreaker_set_score: isDealbreaker ? null : 0 })
          }
        />
        <Tooltip label="Remove option" openDelay={300}>
          <ActionIcon color="gray" size="sm" onClick={onRemove} aria-label="remove option">
            <IconX size={14} stroke={1.5} />
          </ActionIcon>
        </Tooltip>
      </Group>
    </OptionGridRow>
  );
}

// Boolean criteria: exactly one True row and one False row, as text — which
// value matched is data, not a control. Rows synthesize on first edit if the
// saved rubric is missing one.
function BoolRows({
  criterion,
  onChange,
}: {
  criterion: RubricCriterion;
  onChange: (criterion: RubricCriterion) => void;
}) {
  const rows = [true, false].map((boolValue) => {
    const index = criterion.options.findIndex(
      (o) => o.match.op === "bool" && o.match.value === boolValue,
    );
    const option: RubricOption =
      index >= 0
        ? criterion.options[index]
        : { match: { op: "bool", value: boolValue }, delta: 0, dealbreaker_set_score: null };
    return { boolValue, index, option };
  });

  const setBoolOption = (index: number, option: RubricOption) => {
    const options =
      index >= 0
        ? criterion.options.map((o, i) => (i === index ? option : o))
        : [...criterion.options, option];
    onChange({ ...criterion, options });
  };

  return (
    <>
      {rows.map(({ boolValue, index, option }) => {
        const isDealbreaker = isOptionDealbreaker(option);
        return (
          <OptionGridRow key={String(boolValue)}>
            <Text size="sm" fw={500} pl={2}>
              {boolValue ? "True" : "False"}
            </Text>
            {isDealbreaker ? (
              <DealbreakerScoreInput
                value={option.dealbreaker_set_score ?? 0}
                onChange={(next) =>
                  setBoolOption(index, { ...option, dealbreaker_set_score: next })
                }
              />
            ) : (
              <PointsInput
                ariaLabel={`points when ${boolValue}`}
                value={option.delta}
                onChange={(delta) => setBoolOption(index, { ...option, delta })}
              />
            )}
            <DealbreakerToggle
              active={isDealbreaker}
              onToggle={() =>
                setBoolOption(index, {
                  ...option,
                  dealbreaker_set_score: isDealbreaker ? null : 0,
                })
              }
            />
            <div />
          </OptionGridRow>
        );
      })}
    </>
  );
}

export function CriterionCard({
  criterion,
  entry,
  onChange,
  onRemove,
}: {
  criterion: RubricCriterion;
  entry: CatalogEntry;
  onChange: (criterion: RubricCriterion) => void;
  onRemove?: () => void;
}) {
  const isBonus = deriveIsBonus(criterion.options, criterion.unknown_delta);
  const isBoolean = entry.value_schema.type === "boolean";

  const setOption = (index: number, option: RubricOption) => {
    const options = criterion.options.map((o, i) => (i === index ? option : o));
    onChange({ ...criterion, options });
  };

  return (
    <Card>
      <Stack gap="sm">
        <Group gap="xs" wrap="nowrap">
          <Switch
            checked={criterion.enabled}
            onChange={(e) => onChange({ ...criterion, enabled: e.currentTarget.checked })}
            aria-label={`enable ${entry.label}`}
          />
          <CriterionTile entry={entry} />
          <Text fw={600} size="sm" truncate style={{ minWidth: 0 }}>
            {entry.label}
          </Text>
          <Tooltip label={entry.extraction_hint} maw={320} multiline>
            <ActionIcon
              color="gray"
              size="xs"
              variant="subtle"
              aria-label={`info about ${entry.label}`}
            >
              <IconInfoCircle size={14} stroke={1.5} color="var(--mantine-color-dimmed)" />
            </ActionIcon>
          </Tooltip>
          {isBonus && criterion.enabled && <BonusMark />}
          {criterion.non_negotiable !== null && criterion.enabled && (
            <GateMark setScore={criterion.non_negotiable.set_score} />
          )}
          {onRemove && (
            <Tooltip label="Remove custom criterion" openDelay={300}>
              <ActionIcon
                color="gray"
                size="xs"
                variant="subtle"
                aria-label={`remove ${entry.label}`}
                onClick={onRemove}
              >
                <IconTrash size={14} stroke={1.5} />
              </ActionIcon>
            </Tooltip>
          )}
        </Group>

        {criterion.enabled && (
          <Stack gap="xs">
            <OptionGridRow>
              <Text size="xs" c="dimmed">
                When the value is…
              </Text>
              <Text size="xs" c="dimmed">
                Points
              </Text>
            </OptionGridRow>

            {isBoolean ? (
              <BoolRows criterion={criterion} onChange={onChange} />
            ) : (
              <>
                {criterion.options.map((option, index) => (
                  <OptionRow
                    key={index}
                    option={option}
                    entry={entry}
                    onChange={(next) => setOption(index, next)}
                    onRemove={() =>
                      onChange({
                        ...criterion,
                        options: criterion.options.filter((_, i) => i !== index),
                      })
                    }
                  />
                ))}
                <Button
                  variant="subtle"
                  size="xs"
                  w="fit-content"
                  leftSection={<IconPlus size={14} stroke={1.5} />}
                  onClick={() =>
                    onChange({
                      ...criterion,
                      options: [
                        ...criterion.options,
                        {
                          match: {
                            op: entry.value_schema.type === "array" ? "contains_any" : "eq",
                            value: entry.value_schema.type === "array" ? [] : null,
                          },
                          delta: 0,
                          dealbreaker_set_score: null,
                        },
                      ],
                    })
                  }
                >
                  Add option
                </Button>
              </>
            )}

            <Divider my={4} />

            <OptionGridRow>
              <Tooltip
                label="Points applied when the value can't be determined"
                openDelay={300}
                position="top-start"
              >
                <Group gap={6} wrap="nowrap">
                  <IconHelpCircle
                    size={15}
                    stroke={1.5}
                    color="var(--mantine-color-dimmed)"
                  />
                  <Text size="sm" c="dimmed">
                    If unknown
                  </Text>
                </Group>
              </Tooltip>
              <PointsInput
                ariaLabel="unknown delta"
                value={criterion.unknown_delta}
                onChange={(unknown_delta) => onChange({ ...criterion, unknown_delta })}
              />
              <div />
              <div />
            </OptionGridRow>

            <GateControls
              nonNegotiable={criterion.non_negotiable}
              onChange={(non_negotiable) => onChange({ ...criterion, non_negotiable })}
            />
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
