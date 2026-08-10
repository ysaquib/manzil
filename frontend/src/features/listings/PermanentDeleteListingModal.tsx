// Permanently deleting a Listing — the Hunt-local half of a Property (§3).
//
// The confirmation itself is the shared `ConfirmDeleteModal`; what is local
// here is the impact query, which counts what actually dies before anyone is
// asked to type anything, and the active-Job block.
import { Alert, Group, List, Loader, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";

import { ConfirmDeleteModal } from "../../components/ConfirmDeleteModal";
import { ApiError } from "../../lib/apiClient";
import { useListingDeletionImpact, usePermanentDeleteListing } from "./api";

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
  const impact = useListingDeletionImpact(huntId, target?.id ?? null, target !== null);
  const remove = usePermanentDeleteListing(huntId);

  const propertyName = impact.data?.property_name ?? target?.propertyName ?? "";
  const activeJobs = impact.data?.active_jobs ?? 0;
  // Not loaded is not deletable: the operator is being asked to confirm an
  // impact nobody has counted yet.
  const blockedReason =
    activeJobs > 0
      ? `${activeJobs} queued, running, or waiting Job${activeJobs === 1 ? "" : "s"} — cancel or finish them in Tasks first`
      : impact.data === undefined
        ? "still counting the affected records"
        : undefined;

  const permanentlyDelete = () => {
    if (!target) return;
    remove.mutate(
      { listingId: target.id, confirmationName: propertyName },
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
    <ConfirmDeleteModal
      opened={target !== null}
      onClose={onClose}
      noun={{ singular: "listing", plural: "listings" }}
      title="Permanently delete listing?"
      confirmLabel="Permanently delete"
      loading={remove.isPending}
      warning="This removes the Listing and all of its Hunt-local history. The shared Property and any Listing for it in another Hunt are not deleted. A minimal deletion record is retained."
      targets={
        target
          ? [{ id: target.id, label: propertyName, description: "Archived listing", blockedReason }]
          : []
      }
      onConfirm={permanentlyDelete}
    >
      {impact.isLoading && (
        <Group gap="sm">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            Counting affected records…
          </Text>
        </Group>
      )}
      {impact.error && (
        <Alert color="red" title="Couldn't load deletion impact">
          {impact.error.message}
        </Alert>
      )}
      {counts && (
        <List size="sm" spacing="xs">
          <List.Item>
            {counts.unit_groups} Unit Group{counts.unit_groups === 1 ? "" : "s"} and{" "}
            {counts.scores} score record{counts.scores === 1 ? "" : "s"}
          </List.Item>
          <List.Item>
            {counts.manual_values} manual value{counts.manual_values === 1 ? "" : "s"} and{" "}
            {counts.collaboration_records} collaboration record
            {counts.collaboration_records === 1 ? "" : "s"}
          </List.Item>
          <List.Item>
            {counts.task_records} task-history record{counts.task_records === 1 ? "" : "s"}
          </List.Item>
          <List.Item>
            {counts.visits} Visit{counts.visits === 1 ? "" : "s"} containing {counts.visit_records}{" "}
            record{counts.visit_records === 1 ? "" : "s"}
          </List.Item>
          <List.Item>
            {counts.hunt_scoped_extractions} Hunt-scoped custom Extraction
            {counts.hunt_scoped_extractions === 1 ? "" : "s"}
          </List.Item>
        </List>
      )}
    </ConfirmDeleteModal>
  );
}
