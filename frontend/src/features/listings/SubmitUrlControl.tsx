// Submit-URL control (§13.2): URL input + Source Policy Select preset to the
// hunt default — visible but not in the way, since the default is right for
// most submissions. Always visible on the Overview (frontend/AGENTS.md
// affordance hierarchy): submitting listings is the app's most frequent write.
// Duplicate pre-check (m3): a URL already on a Property in this hunt warns
// before enqueueing — saving a pipeline run — but never blocks.
import { Button, Group, Modal, Select, Stack, Text, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { ApiError } from "../../lib/apiClient";
import { SOURCE_POLICIES, type SourcePolicy } from "../../lib/contracts";
import { isDemo } from "../../lib/demo";
import { useDemoCapture } from "../demo/replay/useDemoCapture";
import { ReplayDisclosureModal } from "../demo/replay/ReplayDisclosureModal";
import { useDemoReplay } from "../demo/replay/useDemoReplay";
import { useCreateListing } from "./api";
import { findDuplicateListing } from "./duplicateCheck";
import type { Listing } from "./types";

export function SubmitUrlControl({
  huntId,
  defaultPolicy,
  listings = [],
}: {
  huntId: string;
  defaultPolicy: SourcePolicy;
  /** Loaded hunt listings, for the duplicate pre-check. */
  listings?: Listing[];
}) {
  const createListing = useCreateListing(huntId);
  const [url, setUrl] = useState("");
  const [policy, setPolicy] = useState<SourcePolicy>(defaultPolicy);
  const [duplicateOf, setDuplicateOf] = useState<Listing | null>(null);
  const [replayPrompt, setReplayPrompt] = useState(false);
  const demoCapture = useDemoCapture();
  const replay = useDemoReplay(huntId, demoCapture ? { capture: demoCapture } : {});

  const enqueue = () =>
    createListing.mutate(
      { url, source_policy: policy },
      {
        onSuccess: () => {
          setUrl("");
          notifications.show({
            title: "Listing submitted",
            message: "Manzil is on it — progress lives in the Tasks tab.",
            color: "green",
          });
        },
        onError: (error) =>
          notifications.show({
            title: "Couldn't submit listing",
            message: error instanceof ApiError ? error.message : "Unexpected error",
            color: "red",
          }),
      },
    );

  const submit = () => {
    // Demo mode never enqueues: `submit_listing` rejects the demo subject at
    // function entry and the write guard would refuse the row regardless, so
    // the honest path is to say the link will not be fetched and offer the
    // recording instead (DM-9, DESIGN §3).
    if (isDemo()) {
      if (demoCapture) {
        setReplayPrompt(true);
      } else {
        // No recording in this build. Say so rather than falling through to a
        // write the database will refuse and a toast that would claim success.
        notifications.show({
          title: "Not available in this demo",
          message: "This demo has no recorded ingest to show. Everything else is explorable.",
          color: "yellow",
        });
      }
      return;
    }
    const duplicate = findDuplicateListing(listings, url);
    if (duplicate) {
      setDuplicateOf(duplicate);
      return;
    }
    enqueue();
  };

  const startReplay = () => {
    setReplayPrompt(false);
    setUrl("");
    replay.start();
    notifications.show({
      title: "Playing a recorded ingest",
      message: "Progress lives in the Tasks tab — it will ask you a question part-way through.",
      color: "green",
    });
  };

  return (
    <Group gap="sm" align="flex-end" wrap="wrap">
      <TextInput
        label="Add a listing"
        placeholder="Paste a listing URL"
        value={url}
        onChange={(e) => setUrl(e.currentTarget.value)}
        style={{ flex: 1, minWidth: 240 }}
      />
      <Select
        label="Cross-checking"
        data={SOURCE_POLICIES}
        value={policy}
        onChange={(next) => next && setPolicy(next as SourcePolicy)}
        allowDeselect={false}
        // w={170}
      />
      <Button onClick={submit} disabled={!url.trim() || createListing.isPending}>
        Add listing
      </Button>

      <Modal
        opened={duplicateOf !== null}
        onClose={() => setDuplicateOf(null)}
        title="Already in this hunt"
      >
        <Stack>
          <Text size="sm">
            This URL already belongs to{" "}
            <Text span fw={600}>{duplicateOf?.property.name}</Text>. Submitting it again runs the
            whole pipeline just to find that out.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDuplicateOf(null)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                setDuplicateOf(null);
                enqueue();
              }}
            >
              Submit anyway
            </Button>
          </Group>
        </Stack>
      </Modal>

      {demoCapture && (
        <ReplayDisclosureModal
          capture={demoCapture}
          submittedUrl={url}
          opened={replayPrompt}
          onCancel={() => setReplayPrompt(false)}
          onConfirm={startReplay}
        />
      )}
    </Group>
  );
}
