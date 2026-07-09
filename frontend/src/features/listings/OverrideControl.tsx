// Override control (P1-11, §9.6): a quiet per-criterion affordance — override
// is occasional, so it lives behind a small "edit" button opening a Popover
// (frontend/AGENTS.md hierarchy), never inline clutter. POST then invalidate;
// the async rescore updates the score on the next poll/refetch.
import { ActionIcon, Button, Popover, Stack, TextInput, Tooltip } from "@mantine/core";
import { IconPencil } from "@tabler/icons-react";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { ApiError } from "../../lib/apiClient";
import { useCreateOverride } from "./api";
import { WidgetForSchema } from "../rubric/widgets/widgetForSchema";
import type { ValueSchema } from "../rubric/widgets/types";
import type { WidgetValue } from "../rubric/widgets/types";

export function OverrideControl({
  huntId,
  listingId,
  criterionKey,
  schema,
  currentValue,
}: {
  huntId: string;
  listingId: string;
  criterionKey: string;
  schema: ValueSchema | undefined;
  currentValue: unknown;
}) {
  const createOverride = useCreateOverride(huntId, listingId);
  const [opened, setOpened] = useState(false);
  const [value, setValue] = useState<WidgetValue>(null);
  const [note, setNote] = useState("");

  const open = () => {
    const seed = currentValue;
    setValue(
      typeof seed === "number" || typeof seed === "boolean" || typeof seed === "string"
        ? seed
        : null,
    );
    setNote("");
    setOpened(true);
  };

  const save = () =>
    createOverride.mutate(
      { criterion_key: criterionKey, value, note: note.trim() || null },
      {
        onSuccess: () => {
          setOpened(false);
          notifications.show({
            title: "Override saved",
            message: "Re-scoring — the score updates in a few seconds.",
            color: "green",
          });
        },
        onError: (error) =>
          notifications.show({
            title: "Couldn't save override",
            message: error instanceof ApiError ? error.message : "Unexpected error",
            color: "red",
          }),
      },
    );

  return (
    <Popover opened={opened} onChange={setOpened} width={260} position="bottom-end" withArrow>
      <Popover.Target>
        <Tooltip label="Override this value">
          <ActionIcon color="gray" size="sm" onClick={open} aria-label={`override ${criterionKey}`}>
            <IconPencil size={14} stroke={1.5} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs">
          {schema ? (
            <WidgetForSchema schema={schema} value={value} onChange={setValue} label="New value" />
          ) : (
            <TextInput
              label="New value"
              value={value === null ? "" : String(value)}
              onChange={(e) => setValue(e.currentTarget.value)}
            />
          )}
          <TextInput
            label="Note"
            placeholder="e.g. confirmed by leasing office"
            value={note}
            onChange={(e) => setNote(e.currentTarget.value)}
          />
          <Button size="xs" onClick={save} loading={createOverride.isPending}>
            Save override
          </Button>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
