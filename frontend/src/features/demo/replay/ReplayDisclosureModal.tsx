// The disclosure a demo submission must clear before anything animates
// (DM-9, DESIGN §3: "the substitution is disclosed before the user confirms").
//
// The honest thing to say here is specific, not vague. Three facts, none of
// them softened: the URL will not be fetched, what will play instead is a
// recording of a real run, and the clock is the one part of it that is staged.
import { Alert, Button, Group, List, Modal, Stack, Text } from "@mantine/core";

import type { Capture } from "./capture";
import { describeDuration } from "./replayTiming";
import { replayDisclosure } from "./useDemoReplay";

export function ReplayDisclosureModal({
  capture,
  submittedUrl,
  opened,
  onCancel,
  onConfirm,
}: {
  capture: Capture;
  submittedUrl: string;
  opened: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { realDurationMs, playbackMs, speedup, propertyName } = replayDisclosure(capture);
  const realText = describeDuration(realDurationMs);

  return (
    <Modal opened={opened} onClose={onCancel} title="This demo won't fetch your link">
      <Stack>
        <Text size="sm">
          Manzil isn't going to read{" "}
          <Text span fw={600} style={{ wordBreak: "break-all" }}>
            {submittedUrl}
          </Text>
          . The demo spends no money and writes nothing, so it can't run the pipeline for you.
        </Text>

        <Alert color="ochre" title="What you'll see instead">
          <List size="sm" spacing={4}>
            <List.Item>
              A recording of a real ingest{propertyName ? ` — ${propertyName}` : ""}. Every value
              in it was genuinely extracted from a real page.
            </List.Item>
            <List.Item>
              {realText
                ? `That run took ${realText}. This plays in about ${Math.round(playbackMs / 1000)} seconds`
                : `It plays in about ${Math.round(playbackMs / 1000)} seconds`}
              {speedup && speedup > 1.5 ? ` — roughly ${Math.round(speedup)}× faster than it happened` : ""}
              . The timings are the only staged part.
            </List.Item>
          </List>
        </Alert>

        <Group justify="flex-end">
          <Button variant="default" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={onConfirm}>Play the recording</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
