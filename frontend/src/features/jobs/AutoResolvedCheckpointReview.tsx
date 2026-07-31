import { Group, Stack, Text } from "@mantine/core";
import { IconClockExclamation } from "@tabler/icons-react";

import type { AutoResolvedCheckpoint } from "./api";
import { CheckpointPromptCard } from "./CheckpointPromptCard";

export function AutoResolvedCheckpointReview({
  checkpoint,
  canAnswer,
  answering,
  onAnswer,
}: {
  checkpoint: AutoResolvedCheckpoint;
  canAnswer: boolean;
  answering: boolean;
  onAnswer: (choice: string, text?: string) => void;
}) {
  const choice =
    typeof checkpoint.answer.choice === "string" ? checkpoint.answer.choice : "the default";
  return (
    <Stack gap="xs">
      <Group gap={6} wrap="nowrap" c="clay.7">
        <IconClockExclamation size={15} stroke={1.5} />
        <Text size="xs" fw={600}>
          Auto-resolved after 24 hours with “{choice}”
        </Text>
      </Group>
      <CheckpointPromptCard
        prompt={checkpoint.prompt}
        context={checkpoint.context}
        onAnswer={onAnswer}
        answering={answering}
        readOnly={!canAnswer}
      />
      <Text size="xs" c="dimmed">
        A revised answer creates a correction Job from the original checkpoint and re-scores the
        Listing. The original run stays in History.
      </Text>
    </Stack>
  );
}
