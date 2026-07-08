// Minimal checkpoint answering (P1-13, §10.10): question + option buttons
// rendered inline on the waiting job card. The rich checkpoint UX (screenshot
// beside the buttons, auto-resolve badge, reopen) is P3-11.
import { Button, Group, Stack, Text, TextInput } from "@mantine/core";
import { useState } from "react";

import type { CheckpointPrompt } from "../../lib/contracts";

export const OTHER_PREFIX = "other:";

export function CheckpointPromptCard({
  prompt,
  onAnswer,
  answering,
}: {
  prompt: CheckpointPrompt;
  onAnswer: (choice: string, text?: string) => void;
  answering: boolean;
}) {
  const [otherText, setOtherText] = useState("");
  const plainOptions = prompt.options.filter((o) => !o.startsWith(OTHER_PREFIX));
  const hasOther = prompt.options.some((o) => o.startsWith(OTHER_PREFIX));

  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        {prompt.question}
      </Text>
      <Group gap="xs" wrap="wrap">
        {plainOptions.map((option) => (
          <Button
            key={option}
            size="xs"
            variant={option === prompt.default ? "filled" : "default"}
            disabled={answering}
            onClick={() => onAnswer(option)}
          >
            {option}
          </Button>
        ))}
      </Group>
      {hasOther && (
        <Group gap="xs" wrap="nowrap">
          <TextInput
            size="xs"
            placeholder="Something else…"
            value={otherText}
            onChange={(e) => setOtherText(e.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <Button
            size="xs"
            variant="default"
            disabled={!otherText.trim() || answering}
            onClick={() => onAnswer("other", otherText.trim())}
          >
            Answer
          </Button>
        </Group>
      )}
    </Stack>
  );
}
