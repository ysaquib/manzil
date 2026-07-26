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
    const duplicate = findDuplicateListing(listings, url);
    if (duplicate) {
      setDuplicateOf(duplicate);
      return;
    }
    enqueue();
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
    </Group>
  );
}
