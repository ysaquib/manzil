// Category heading for a block of rubric cards: serif title (UI_DESIGN §1
// "serif for identity"), a short rule in the category's hue that runs out into
// a neutral hairline, and a dimmed count on the right.
//
// The rule is decorative, so it is a pair of Boxes rather than an <hr> — it
// separates nothing semantically, it just carries the category's colour across
// the page (UI Decision Log 2026-07-25).
import { Box, Group, Text, Title } from "@mantine/core";

import { categoryColor } from "./criterionCategory";

export function CriterionGroupHeader({
  label,
  category,
  count,
}: {
  label: string;
  category: string;
  count: string;
}) {
  return (
    <Group gap="sm" wrap="nowrap" align="center">
      <Title order={4} style={{ flexShrink: 0 }}>
        {label}
      </Title>
      <Group gap={0} wrap="nowrap" style={{ flex: 1, minWidth: 0 }} aria-hidden>
        <Box w={44} h={2} bg={`${categoryColor(category)}.6`} style={{ borderRadius: 1 }} />
        <Box h={1} bg="var(--mantine-color-default-border)" style={{ flex: 1 }} />
      </Group>
      <Text size="xs" c="dimmed" ff="monospace" style={{ flexShrink: 0 }}>
        {count}
      </Text>
    </Group>
  );
}
