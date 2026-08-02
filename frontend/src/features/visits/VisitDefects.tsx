// The defect log (VC-4, DESIGN §9.7).
//
// Most rows here were not typed: marking a Check as a problem promotes into one,
// carrying its unit and originating item. That is the whole design — the source
// document's defect table is one nobody transcribes into mid-tour.
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Card,
  Group,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { IconFlag, IconPlus, IconTrash, IconWand } from "@tabler/icons-react";
import { useState } from "react";

import { SEVERITY_META, SEVERITY_ORDER, toneFor } from "./statusColors";

import {
  useCreateVisitDefect,
  useDeleteVisitDefect,
  usePatchVisitDefect,
  useVisitDefects,
} from "./api";
import type { VisitDefect, VisitDefectSeverity, VisitUnit } from "./types";
import classes from "./VisitDefects.module.css";

function unitLabel(units: VisitUnit[], unitId: string | null): string {
  if (unitId === null) return "The building";
  return units.find((unit) => unit.id === unitId)?.label ?? "Unknown unit";
}

/** The glyph per level. Colour reinforces; the shape and the word carry it. */
const SEVERITY_GLYPH: Record<VisitDefectSeverity, string> = {
  noted: "○",
  minor: "◐",
  major: "▲",
  dealbreaker: "✖",
};

/**
 * Four named levels replacing five stars (VC-10).
 *
 * Stars asked you to rate a defect out of five on a scale nobody had defined,
 * and read as *quality* everywhere else in this app — so on a defect, more
 * stars looked like better news. Each level here carries a word, a glyph and a
 * band of the status ramp, and says in plain words what it means.
 *
 * On a record the unchosen levels are dropped rather than greyed: an empty
 * outline beside the answer is an affordance that does nothing.
 */
function SeverityPicker({
  value,
  readOnly,
  onChange,
}: {
  value: VisitDefectSeverity | null;
  readOnly?: boolean;
  onChange: (next: VisitDefectSeverity) => void;
}) {
  const shown = readOnly ? SEVERITY_ORDER.filter((level) => level === value) : SEVERITY_ORDER;

  if (readOnly && shown.length === 0) {
    return (
      <Text size="xs" c="dimmed" fs="italic">
        Unrated
      </Text>
    );
  }

  return (
    <Stack gap={3}>
      <Group gap={4} wrap="wrap" role="group" aria-label="Severity">
        {shown.map((level) => {
          const meta = SEVERITY_META[level];
          const active = value === level;
          return (
            <Tooltip key={level} label={meta.help} disabled={readOnly}>
              <Button
                size="compact-sm"
                // `light` in both states rather than `filled` when chosen: the
                // filled variant's text colour is picked by autoContrast, which
                // flips between schemes on exactly these mid-tone earthy hues.
                variant={active ? "light" : "default"}
                color={active ? meta.color : "gray"}
                className={active ? classes.severityOn : undefined}
                aria-pressed={active}
                onClick={() => !readOnly && onChange(level)}
                leftSection={<span aria-hidden>{SEVERITY_GLYPH[level]}</span>}
                style={readOnly ? { cursor: "default" } : undefined}
              >
                {meta.label}
              </Button>
            </Tooltip>
          );
        })}
      </Group>
      {value !== null && (
        <Text size="xs" c="dimmed">
          {SEVERITY_META[value].help}
        </Text>
      )}
      {value === null && !readOnly && (
        <Text size="xs" c="dimmed" fs="italic">
          Unrated — pick one when you know
        </Text>
      )}
    </Stack>
  );
}

function DefectRow({
  defect,
  units,
  visitId,
  readOnly,
}: {
  defect: VisitDefect;
  units: VisitUnit[];
  visitId: string;
  readOnly?: boolean;
}) {
  const patch = usePatchVisitDefect(visitId);
  const remove = useDeleteVisitDefect(visitId);

  return (
    <Group align="flex-start" wrap="nowrap" gap="sm" py="xs">
      <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
        <Group gap={6} wrap="wrap">
          <Text size="sm" fw={500}>
            {defect.title}
          </Text>
          <Badge variant="light" color="gray" size="xs" radius="sm">
            {unitLabel(units, defect.visit_unit_id)}
          </Badge>
          {defect.from_item_key && (
            <Tooltip label="Logged automatically when you marked that check a problem">
              <Badge
                variant="outline"
                color="gray"
                size="xs"
                radius="sm"
                leftSection={<IconWand size={10} />}
              >
                From a check
              </Badge>
            </Tooltip>
          )}
          {defect.promised_in_writing && (
            <Badge variant="light" color="green" size="xs" radius="sm">
              Promised in writing
            </Badge>
          )}
        </Group>
        {defect.note && (
          <Text size="xs" c="dimmed">
            {defect.note}
          </Text>
        )}
        <Group gap="md" wrap="wrap" mt={2}>
          <Stack gap={4}>
            <Text size="xs" c="dimmed">
              Severity
            </Text>
            <SeverityPicker
              value={defect.severity}
              readOnly={readOnly}
              onChange={(next) =>
                patch.mutate({
                  defectId: defect.id,
                  // Choosing the current level clears it back to unrated, which
                  // is a real state on a tour you are still walking.
                  body: { severity: next === defect.severity ? null : next },
                })
              }
            />
          </Stack>
          {/* On a record the switch says nothing the green badge above has not
              already said, and greyed out it says it less legibly. */}
          {!readOnly && (
            <Switch
              size="xs"
              label="Promised in writing"
              checked={defect.promised_in_writing}
              onChange={(event) =>
                patch.mutate({
                  defectId: defect.id,
                  body: { promised_in_writing: event.currentTarget.checked },
                })
              }
            />
          )}
        </Group>
      </Stack>
      {!readOnly && (
        <Tooltip label="Remove — the check keeps its answer">
          <ActionIcon
            color="red"
            variant="subtle"
            aria-label={`Remove defect: ${defect.title}`}
            loading={remove.isPending}
            onClick={() => remove.mutate(defect.id)}
          >
            <IconTrash size={15} />
          </ActionIcon>
        </Tooltip>
      )}
    </Group>
  );
}

export function VisitDefects({
  visitId,
  units,
  activeUnitId,
  readOnly,
}: {
  visitId: string;
  units: VisitUnit[];
  activeUnitId: string | null;
  readOnly?: boolean;
}) {
  const defectsQuery = useVisitDefects(visitId);
  const create = useCreateVisitDefect(visitId);
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [onUnit, setOnUnit] = useState(true);

  const defects = defectsQuery.data ?? [];
  const promoted = defects.filter((defect) => defect.from_item_key).length;

  return (
    <Card>
      <Stack gap="sm">
        <Group justify="space-between">
          <Group gap={8}>
            <IconFlag size={16} />
            <Text fw={600} ff="var(--mantine-font-family-headings)" size="md">
              Defect log
            </Text>
          </Group>
          <Badge
            variant={toneFor(defects.length ? "problem" : "empty").variant}
            color={toneFor(defects.length ? "problem" : "empty").color}
            radius="sm"
          >
            {defects.length === 1 ? "1 defect" : `${defects.length} defects`}
          </Badge>
        </Group>

        {promoted > 0 && (
          <Text size="xs" c="dimmed">
            {promoted === 1 ? "One of these" : `${promoted} of these`} logged{" "}
            {promoted === 1 ? "itself" : "themselves"} from a failed check.
          </Text>
        )}

        {defects.length === 0 ? (
          <Text size="sm" c="dimmed" fs="italic">
            Nothing logged yet. Marking a check as a problem records one here
            automatically, with its unit attached.
          </Text>
        ) : (
          <Stack gap={0}>
            {defects.map((defect, index) => (
              <Box
                key={defect.id}
                style={
                  index === 0
                    ? undefined
                    : { borderTop: "1px solid var(--mantine-color-default-border)" }
                }
              >
                <DefectRow
                  defect={defect}
                  units={units}
                  visitId={visitId}
                  readOnly={readOnly}
                />
              </Box>
            ))}
          </Stack>
        )}

        {!readOnly &&
          (adding ? (
            <Card withBorder bg="var(--mantine-color-default-hover)">
              <Stack gap="sm">
                <TextInput
                  label="What's wrong?"
                  placeholder="Water stain under the kitchen sink"
                  value={title}
                  onChange={(event) => setTitle(event.currentTarget.value)}
                  data-autofocus
                />
                {activeUnitId && (
                  <Switch
                    size="sm"
                    label={`Attach to ${unitLabel(units, activeUnitId)}`}
                    description="Turn off for something wrong with the building"
                    checked={onUnit}
                    onChange={(event) => setOnUnit(event.currentTarget.checked)}
                  />
                )}
                <Group>
                  <Button
                    size="compact-sm"
                    disabled={!title.trim()}
                    loading={create.isPending}
                    onClick={() =>
                      create.mutate(
                        {
                          title: title.trim(),
                          visit_unit_id: onUnit ? activeUnitId : null,
                          promised_in_writing: false,
                        },
                        {
                          onSuccess: () => {
                            setTitle("");
                            setAdding(false);
                          },
                        },
                      )
                    }
                  >
                    Log it
                  </Button>
                  <Button size="compact-sm" variant="subtle" onClick={() => setAdding(false)}>
                    Cancel
                  </Button>
                </Group>
              </Stack>
            </Card>
          ) : (
            <Button
              variant="light"
              size="compact-sm"
              w="fit-content"
              leftSection={<IconPlus size={14} />}
              onClick={() => setAdding(true)}
            >
              Log something else
            </Button>
          ))}
      </Stack>
    </Card>
  );
}
