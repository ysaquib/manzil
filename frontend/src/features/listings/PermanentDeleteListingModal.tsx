import {
  Alert,
  Button,
  Group,
  List,
  Loader,
  Modal,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useEffect, useState } from "react";

import { ApiError } from "../../lib/apiClient";
import {
  useListingDeletionImpact,
  usePermanentDeleteListing,
} from "./api";

export interface PermanentDeleteTarget {
  id: string;
  propertyName: string;
}

export function PermanentDeleteListingModal({
  huntId,
  target,
  onClose,
  onDeleted,
}: {
  huntId: string;
  target: PermanentDeleteTarget | null;
  onClose: () => void;
  onDeleted: (listingId: string) => void;
}) {
  const [confirmation, setConfirmation] = useState("");
  const impact = useListingDeletionImpact(huntId, target?.id ?? null, target !== null);
  const remove = usePermanentDeleteListing(huntId);

  useEffect(() => {
    setConfirmation("");
  }, [target?.id]);

  const close = () => {
    if (!remove.isPending) onClose();
  };
  const propertyName = impact.data?.property_name ?? target?.propertyName ?? "";
  const activeJobs = impact.data?.active_jobs ?? 0;
  const confirmed = target !== null && impact.data !== undefined && confirmation === propertyName;
  const blocked = activeJobs > 0;

  const permanentlyDelete = () => {
    if (!target || !confirmed || blocked) return;
    remove.mutate(
      { listingId: target.id, confirmationName: confirmation },
      {
        onSuccess: () => {
          notifications.show({
            message: `${propertyName} permanently deleted from this Hunt.`,
            color: "green",
          });
          onDeleted(target.id);
          onClose();
        },
        onError: (error) =>
          notifications.show({
            title: "Couldn't permanently delete listing",
            message: error instanceof ApiError ? error.message : "Unexpected error",
            color: "red",
          }),
      },
    );
  };

  const counts = impact.data?.counts;
  return (
    <Modal
      opened={target !== null}
      onClose={close}
      title="Permanently delete listing?"
      closeOnClickOutside={!remove.isPending}
      closeOnEscape={!remove.isPending}
    >
      <Stack>
        <Alert color="red" title="This cannot be undone">
          This removes the Listing and all of its Hunt-local history. The shared Property and any
          Listing for it in another Hunt are not deleted. A minimal deletion record is retained.
        </Alert>

        {impact.isLoading && (
          <Group gap="sm">
            <Loader size="sm" />
            <Text size="sm" c="dimmed">Counting affected records…</Text>
          </Group>
        )}
        {impact.error && (
          <Alert color="red" title="Couldn't load deletion impact">
            {impact.error.message}
          </Alert>
        )}
        {counts && (
          <List size="sm" spacing="xs">
            <List.Item>{counts.unit_groups} Unit Group{counts.unit_groups === 1 ? "" : "s"} and {counts.scores} score record{counts.scores === 1 ? "" : "s"}</List.Item>
            <List.Item>{counts.manual_values} manual value{counts.manual_values === 1 ? "" : "s"} and {counts.collaboration_records} collaboration record{counts.collaboration_records === 1 ? "" : "s"}</List.Item>
            <List.Item>{counts.task_records} task-history record{counts.task_records === 1 ? "" : "s"}</List.Item>
            <List.Item>{counts.visits} Visit{counts.visits === 1 ? "" : "s"} containing {counts.visit_records} record{counts.visit_records === 1 ? "" : "s"}</List.Item>
            <List.Item>{counts.hunt_scoped_extractions} Hunt-scoped custom Extraction{counts.hunt_scoped_extractions === 1 ? "" : "s"}</List.Item>
          </List>
        )}
        {blocked && (
          <Alert color="orange" title="Active work must finish first">
            This Listing has {activeJobs} queued, running, or waiting Job{activeJobs === 1 ? "" : "s"}. Cancel or finish them in Tasks before deleting it.
          </Alert>
        )}

        <TextInput
          label={`Type “${propertyName}” to confirm`}
          value={confirmation}
          onChange={(event) => setConfirmation(event.currentTarget.value)}
          autoComplete="off"
          disabled={remove.isPending}
          error={confirmation.length > 0 && !confirmed ? "Property name does not match" : undefined}
        />

        <Group justify="flex-end">
          <Button variant="default" onClick={close} disabled={remove.isPending}>Cancel</Button>
          <Button
            color="red"
            onClick={permanentlyDelete}
            loading={remove.isPending}
            disabled={!confirmed || blocked || impact.isLoading || Boolean(impact.error)}
          >
            Permanently delete
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
