// One criterion's rubric editor (§13.2): options table with delta steppers,
// unknown-delta row, per-option dealbreaker toggles, non-negotiable gate.
// is_bonus is derived and display-only (§9.2).
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  NumberInput,
  Stack,
  Switch,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconBan,
  IconInfoCircle,
  IconPlus,
  IconQuestionMark,
  IconShieldCheck,
  IconSparkles,
  IconX,
} from "@tabler/icons-react";

import type { RubricOption } from "../../lib/contracts";
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
    <Group gap="sm" align="flex-end" wrap="wrap" justify="space-between">
      <OptionMatchEditor
        match={option.match}
        schema={entry.value_schema}
        onChange={(match) => onChange({ ...option, match })}
      />
      <Group gap="sm" align="flex-end" wrap="wrap">
        <Tooltip label="Points">
          <NumberInput
            aria-label="option delta"
            size="xs"
            w={90}
            step={0.5}
            value={option.delta}
            onChange={(next) => onChange({ ...option, delta: typeof next === "number" ? next : 0 })}
            disabled={isDealbreaker}
            rightSection={
              <Text size="xs" c="dimmed" pr={4}>
                pts
              </Text>
            }
            rightSectionWidth={28}
          />
        </Tooltip>
        <Tooltip label="Dealbreaker — matching this option sets the score directly">
          <Switch
            size="xs"
            aria-label="dealbreaker"
            checked={isDealbreaker}
            onChange={(e) =>
              onChange({ ...option, dealbreaker_set_score: e.currentTarget.checked ? 0 : null })
            }
            onLabel={<IconBan size={12} stroke={1.5} />}
            offLabel={<IconBan size={12} stroke={1.5} color="var(--mantine-color-dimmed)" />}
          />
        </Tooltip>
        {isDealbreaker && (
          <Tooltip label="Score to set when this option matches">
            <NumberInput
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
          </Tooltip>
        )}
        <Tooltip label="Remove option">
          <ActionIcon color="gray" size="sm" onClick={onRemove} aria-label="remove option">
            <IconX size={14} stroke={1.5} />
          </ActionIcon>
        </Tooltip>
      </Group>
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
    <Card h="100%">
      <Stack gap="sm">
        <Group justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Switch
              checked={criterion.enabled}
              onChange={(e) => onChange({ ...criterion, enabled: e.currentTarget.checked })}
              aria-label={`enable ${entry.label}`}
            />
            <Group gap="xs" wrap="wrap">
              <Text fw={600} size="sm">
                {entry.label}
              </Text>
              <Tooltip label={entry.extraction_hint}>
                <ActionIcon
                  color="gray"
                  size="xs"
                  variant="subtle"
                  aria-label={`info about ${entry.label}`}
                >
                  <IconInfoCircle size={14} stroke={1.5} color="var(--mantine-color-dimmed)" />
                </ActionIcon>
              </Tooltip>
              {isBonus && criterion.enabled && (
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
              {criterion.non_negotiable !== null && criterion.enabled && (
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
          </Group>
        </Group>

        {criterion.enabled && (
          <Stack gap="xs" mt="xs">
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
                variant="subtle"
                size="xs"
                leftSection={<IconPlus size={14} stroke={1.5} />}
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
                Add
              </Button>
            </Group>
            <Group gap="sm" align="flex-end" mt="md" wrap="wrap">
              <Tooltip label="Points when the value can't be determined">
                <Group gap={4} align="flex-end">
                  <IconQuestionMark
                    size={16}
                    stroke={1.5}
                    color="var(--mantine-color-dimmed)"
                    style={{ marginBottom: 6 }}
                  />
                  <NumberInput
                    aria-label="unknown delta"
                    size="xs"
                    w={90}
                    step={0.5}
                    value={criterion.unknown_delta}
                    onChange={(next) =>
                      onChange({ ...criterion, unknown_delta: typeof next === "number" ? next : 0 })
                    }
                    rightSection={
                      <Text size="xs" c="dimmed" pr={4}>
                        pts
                      </Text>
                    }
                    rightSectionWidth={28}
                  />
                </Group>
              </Tooltip>
              <GateControls
                nonNegotiable={criterion.non_negotiable}
                onChange={(non_negotiable) => onChange({ ...criterion, non_negotiable })}
              />
            </Group>
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
