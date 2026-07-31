// Checkpoint answering (§10.10): the decision, compact evidence quote, and
// Source link stay together. P3-11 deliberately uses this text context instead
// of storing full-page screenshots.
import { Anchor, Button, Code, Group, Paper, Stack, Text, TextInput } from "@mantine/core";
import { IconExternalLink } from "@tabler/icons-react";
import { useState } from "react";

import type { components } from "../../lib/generated/api";
import type { CheckpointContext } from "./api";

type CheckpointPrompt = components["schemas"]["CheckpointPrompt"];

export const OTHER_PREFIX = "other:";

function valueLabel(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "Unknown";
  return JSON.stringify(value);
}

function sourceLabel(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "Source";
  }
}

export function CheckpointContextPanel({ context }: { context?: CheckpointContext | null }) {
  const evidence = context?.evidence ?? [];
  const fallbackUrl = context?.source_url ?? null;
  if (evidence.length === 0 && !fallbackUrl) return null;

  return (
    <Stack gap={6}>
      {evidence.map((item, index) => (
        <Paper key={`${item.source_url ?? "source"}:${index}`} withBorder p="xs">
          <Stack gap={4}>
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <Code>{valueLabel(item.value)}</Code>
              {item.source_url && (
                <Anchor
                  href={item.source_url}
                  target="_blank"
                  rel="noreferrer"
                  size="xs"
                  style={{ whiteSpace: "nowrap" }}
                >
                  {sourceLabel(item.source_url)} <IconExternalLink size={11} />
                </Anchor>
              )}
            </Group>
            {item.evidence_quote && (
              <Text size="xs" c="dimmed" fs="italic">
                “{item.evidence_quote}”
              </Text>
            )}
          </Stack>
        </Paper>
      ))}
      {evidence.length === 0 && fallbackUrl && (
        <Anchor href={fallbackUrl} target="_blank" rel="noreferrer" size="xs">
          Open {sourceLabel(fallbackUrl)} <IconExternalLink size={11} />
        </Anchor>
      )}
    </Stack>
  );
}

export function CheckpointPromptCard({
  prompt,
  context,
  onAnswer,
  answering,
  readOnly = false,
}: {
  prompt: CheckpointPrompt;
  context?: CheckpointContext | null;
  onAnswer: (choice: string, text?: string) => void;
  answering: boolean;
  readOnly?: boolean;
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
      <CheckpointContextPanel context={context} />
      {readOnly && (
        <Text size="xs" c="dimmed">
          The Listing submitter, a Curator, or the Owner can revise this answer.
        </Text>
      )}
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
              disabled={answering || readOnly}
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
            disabled={!otherText.trim() || answering || readOnly}
            onClick={() => onAnswer("other", otherText.trim())}
          >
            Answer
          </Button>
        </Group>
      )}
    </Stack>
  );
}
