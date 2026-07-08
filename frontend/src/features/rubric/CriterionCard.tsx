// One criterion's rubric editor (§13.2): options table with delta steppers,
// unknown-delta row, per-option dealbreaker toggles, non-negotiable gate.
// is_bonus is derived and display-only (§9.2).
import {
  ActionIcon,
  Badge,
  Button,
  Divider,
  Group,
  NumberInput,
  Paper,
  Stack,
  Switch,
  Text,
  Tooltip,
} from "@mantine/core";

import type { RubricOption } from "../../lib/contracts";
import { semantic } from "../../theme";
import type { CatalogEntry, RubricCriterion } from "./api";
import { GateControls } from "./GateControls";
import { OptionMatchEditor } from "./OptionMatchEditor";
import { deriveIsBonus } from "./rubricDraft";

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
  const isDealbreaker = option.dealbreaker_set_score !== null;
  return (
    <Group gap="sm" align="flex-end" wrap="wrap">
      <OptionMatchEditor
        match={option.match}
        schema={entry.value_schema}
        onChange={(match) => onChange({ ...option, match })}
      />
      <NumberInput
        label="points"
        aria-label="option delta"
        size="xs"
        w={90}
        step={0.5}
        value={option.delta}
        onChange={(next) => onChange({ ...option, delta: typeof next === "number" ? next : 0 })}
        disabled={isDealbreaker}
      />
      <Switch
        size="xs"
        label="Dealbreaker"
        checked={isDealbreaker}
        onChange={(e) =>
          onChange({ ...option, dealbreaker_set_score: e.currentTarget.checked ? 0 : null })
        }
      />
      {isDealbreaker && (
        <NumberInput
          label="set score to"
          aria-label="dealbreaker set score"
          size="xs"
          w={90}
          min={0}
          max={15}
          value={option.dealbreaker_set_score ?? 0}
          onChange={(next) =>
            onChange({ ...option, dealbreaker_set_score: typeof next === "number" ? next : 0 })
          }
        />
      )}
      <Tooltip label="Remove option">
        <ActionIcon variant="subtle" color="gray" size="sm" onClick={onRemove} aria-label="remove option">
          ✕
        </ActionIcon>
      </Tooltip>
    </Group>
  );
}

export function CriterionCard({
  criterion,
  entry,
  onChange,
}: {
  criterion: RubricCriterion;
  entry: CatalogEntry;
  onChange: (criterion: RubricCriterion) => void;
}) {
  const isBonus = deriveIsBonus(criterion.options, criterion.unknown_delta);

  const setOption = (index: number, option: RubricOption) => {
    const options = criterion.options.map((o, i) => (i === index ? option : o));
    onChange({ ...criterion, options });
  };

  return (
    <Paper p="md">
      <Stack gap="sm">
        <Group justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Switch
              checked={criterion.enabled}
              onChange={(e) => onChange({ ...criterion, enabled: e.currentTarget.checked })}
              aria-label={`enable ${entry.label}`}
            />
            <div>
              <Group gap="xs">
                <Text fw={600} size="sm">
                  {entry.label}
                </Text>
                {isBonus && criterion.enabled && (
                  <Badge size="xs" variant="light" color="green">
                    bonus
                  </Badge>
                )}
                {criterion.non_negotiable !== null && criterion.enabled && (
                  <Badge size="xs" variant="light" color={semantic.danger}>
                    gate
                  </Badge>
                )}
              </Group>
              <Text size="xs" c="dimmed">
                {entry.extraction_hint}
              </Text>
            </div>
          </Group>
        </Group>

        {criterion.enabled && (
          <>
            <Divider />
            <Stack gap="xs">
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
              <Group>
                <Button
                  variant="light"
                  size="xs"
                  onClick={() =>
                    onChange({
                      ...criterion,
                      options: [
                        ...criterion.options,
                        {
                          match: {
                            op: entry.value_schema.type === "boolean" ? "bool" : "eq",
                            value: null,
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
              </Group>
              <Group gap="sm" align="flex-end">
                <NumberInput
                  label="If unknown"
                  description="points when the value can't be determined"
                  size="xs"
                  w={160}
                  step={0.5}
                  value={criterion.unknown_delta}
                  onChange={(next) =>
                    onChange({ ...criterion, unknown_delta: typeof next === "number" ? next : 0 })
                  }
                />
                <GateControls
                  nonNegotiable={criterion.non_negotiable}
                  onChange={(non_negotiable) => onChange({ ...criterion, non_negotiable })}
                />
              </Group>
            </Stack>
          </>
        )}
      </Stack>
    </Paper>
  );
}
