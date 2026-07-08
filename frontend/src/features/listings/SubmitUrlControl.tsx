// Submit-URL control (§13.2): URL input + Source Policy Select preset to the
// hunt default — visible but not in the way, since the default is right for
// most submissions. Always visible on the Overview (frontend/AGENTS.md
// affordance hierarchy): submitting listings is the app's most frequent write.
import { Button, Group, Select, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { ApiError } from "../../lib/apiClient";
import { SOURCE_POLICIES, type SourcePolicy } from "../../lib/contracts";
import { useCreateListing } from "./api";

export function SubmitUrlControl({
  huntId,
  defaultPolicy,
}: {
  huntId: string;
  defaultPolicy: SourcePolicy;
}) {
  const createListing = useCreateListing(huntId);
  const [url, setUrl] = useState("");
  const [policy, setPolicy] = useState<SourcePolicy>(defaultPolicy);

  const submit = () =>
    createListing.mutate(
      { url, source_policy: policy },
      {
        onSuccess: () => {
          setUrl("");
          notifications.show({
            title: "Listing submitted",
            message: "Ingestion started — progress is on the Tasks tab.",
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
        w={230}
      />
      <Button onClick={submit} disabled={!url.trim() || createListing.isPending}>
        Add listing
      </Button>
    </Group>
  );
}
