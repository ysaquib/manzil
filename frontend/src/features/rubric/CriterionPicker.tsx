// Criteria in a category that aren't scored, as one strip of add-pills
// (UI Decision Log 2026-07-25).
//
// Before this, every unscored criterion rendered a full card holding nothing but
// a switch and a label — 28 near-empty boxes on a hunt scoring three criteria,
// and the equal-height grid dragged a void along beside any card that *was*
// scored. A pill has exactly one action, so it's a Button, not a toggle: the
// switch to turn a criterion back off lives on the card it becomes.
import { Button, Group, Stack, Text } from "@mantine/core";

import type { CatalogEntry } from "./api";
import { CriterionTile } from "./criterionIcon";
import classes from "./CriterionPicker.module.css";

export function CriterionPicker({
  entries,
  onEnable,
}: {
  entries: CatalogEntry[];
  onEnable: (entry: CatalogEntry) => void;
}) {
  if (entries.length === 0) return null;

  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed">
        Not scored — click to add
      </Text>
      <Group gap="xs">
        {entries.map((entry) => (
          <Button
            key={entry.key}
            className={classes.pill}
            variant="default"
            size="xs"
            radius="xl"
            leftSection={<CriterionTile entry={entry} size={18} variant="transparent" />}
            onClick={() => onEnable(entry)}
          >
            {entry.label}
          </Button>
        ))}
      </Group>
    </Stack>
  );
}
