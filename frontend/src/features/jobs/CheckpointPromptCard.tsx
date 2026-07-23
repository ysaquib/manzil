// Minimal checkpoint answering (P1-13, §10.10): question + option buttons
// rendered inline on the waiting job card. The rich checkpoint UX (screenshot
// beside the buttons, auto-resolve badge, reopen) is P3-11.
import { Button, Group, Stack, Text, TextInput } from "@mantine/core";
import { useState } from "react";

import type { components } from "../../lib/generated/api";

type CheckpointPrompt = components["schemas"]["CheckpointPrompt"];

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
  const options = prompt.options ?? [];
  const plainOptions = options.filter((o) => !o.startsWith(OTHER_PREFIX));
  const hasOther = options.some((o) => o.startsWith(OTHER_PREFIX));

  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        {prompt.question}
      </Text>
      <Group gap="xs" wrap="wrap">
        {plainOptions.map((option) => {
          const isDefault = option === prompt.default;
          return (
            <Button
              key={option}
              size="xs"
              // The default option is the confirming action — tinted to the
              // waiting/ochre family so it harmonizes with the checkpoint panel
              // instead of clashing as the purple primary.
              variant={isDefault ? "filled" : "default"}
              color={isDefault ? "yellow" : undefined}
              disabled={answering}
              onClick={() => onAnswer(option)}
            >
              {option}
            </Button>
          );
        })}
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
