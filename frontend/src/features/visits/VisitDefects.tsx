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
  Rating,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { IconFlag, IconPlus, IconTrash, IconWand } from "@tabler/icons-react";
import { useState } from "react";

import {
  useCreateVisitDefect,
  useDeleteVisitDefect,
  usePatchVisitDefect,
  useVisitDefects,
} from "./api";
import type { VisitDefect, VisitUnit } from "./types";

function unitLabel(units: VisitUnit[], unitId: string | null): string {
  if (unitId === null) return "The building";
  return units.find((unit) => unit.id === unitId)?.label ?? "Unknown unit";
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
          <Group gap={6}>
            <Text size="xs" c="dimmed">
              Severity
            </Text>
            <Rating
              size="xs"
              color="red"
              value={defect.severity ?? 0}
              readOnly={readOnly}
              onChange={(value) =>
                patch.mutate({
                  defectId: defect.id,
                  // Clicking the current rating clears it back to unrated,
                  // which is a real state on a tour you are still walking.
                  body: { severity: value === defect.severity ? null : value },
                })
              }
            />
            {defect.severity === null && (
              <Text size="xs" c="dimmed" fs="italic">
                unrated
              </Text>
            )}
          </Group>
          <Switch
            size="xs"
            label="Promised in writing"
            checked={defect.promised_in_writing}
            disabled={readOnly}
            onChange={(event) =>
              patch.mutate({
                defectId: defect.id,
                body: { promised_in_writing: event.currentTarget.checked },
              })
            }
          />
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
          <Badge variant="light" color={defects.length ? "red" : "gray"} radius="sm">
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
