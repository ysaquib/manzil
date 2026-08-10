// Archived-listings view (m7, §13.2): the `status = archived` rows the active
// Overview hides — archiving is the app's soft delete, so this is where a
// wrong archive gets undone. One row per Listing (unit groups don't matter
// for restore). Restore is Owner-only server-side, like archive.
import { Alert, Button, Card, Center, Group, Loader, Stack, Table, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArchive, IconRestore, IconTrash } from "@tabler/icons-react";
import { useState } from "react";

import { ApiError } from "../../lib/apiClient";
import { propertyLocationLabel } from "./locality";
import { useArchivedListings, usePatchListingStatus } from "./api";
import { useCompareSet } from "./compareSet";
import {
  PermanentDeleteListingModal,
  type PermanentDeleteTarget,
} from "./PermanentDeleteListingModal";

export function ArchivedListings({
  huntId,
  canManage,
}: {
  huntId: string;
  canManage: boolean;
}) {
  const { data: listings, isLoading, error } = useArchivedListings(huntId, true);
  const patchStatus = usePatchListingStatus(huntId);
  const compare = useCompareSet(huntId);
  const [deleteTarget, setDeleteTarget] = useState<PermanentDeleteTarget | null>(null);

  const restore = (listingId: string, name: string) =>
    patchStatus.mutate(
      { listingId, status: "active" },
      {
        onSuccess: () =>
          notifications.show({ message: `${name} restored to the Overview.`, color: "green" }),
        onError: (err) =>
          notifications.show({
            title: "Couldn't restore listing",
            message: err instanceof ApiError ? err.message : "Unexpected error",
            color: "red",
          }),
      },
    );

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  if (error) {
    return (
      <Alert color="red" title="Couldn't load archived listings">
        {error.message} — try reloading the page.
      </Alert>
    );
  }
  if (!listings || listings.length === 0) {
    return (
      <Card py="xl">
        <Stack align="center" gap="sm">
          <IconArchive size={32} stroke={1.5} color="var(--mantine-color-dimmed)" />
          <Text ta="center" c="dimmed">
            Nothing archived. Rows archived from the Overview land here and can be restored.
          </Text>
        </Stack>
      </Card>
    );
  }

  return (
    <>
      <Table striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Property</Table.Th>
            <Table.Th>City</Table.Th>
            <Table.Th aria-label="row actions" />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {listings.map((listing) => (
            <Table.Tr key={listing.id}>
            <Table.Td>
              <Text size="sm" fw={600}>
                {listing.property.name}
              </Text>
              <Text size="xs" c="dimmed">
                {listing.property.canonical_address}
              </Text>
            </Table.Td>
            <Table.Td>
              <Text size="sm">
                {propertyLocationLabel(listing.property) === "Unknown"
                  ? "—"
                  : propertyLocationLabel(listing.property)}
              </Text>
            </Table.Td>
            <Table.Td width={220}>
              {canManage && (
                <Group gap="xs" justify="flex-end" wrap="nowrap">
                  <Button
                    variant="light"
                    size="xs"
                    leftSection={<IconRestore size={14} stroke={1.5} />}
                    loading={patchStatus.isPending}
                    onClick={() => restore(listing.id, listing.property.name)}
                  >
                    Restore
                  </Button>
                  <Button
                    variant="subtle"
                    color="red"
                    size="xs"
                    leftSection={<IconTrash size={14} stroke={1.5} />}
                    onClick={() => setDeleteTarget({
                      id: listing.id,
                      propertyName: listing.property.name,
                    })}
                  >
                    Delete permanently
                  </Button>
                </Group>
              )}
            </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <PermanentDeleteListingModal
        huntId={huntId}
        target={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onDeleted={(listingId) => compare.removeListing(listingId)}
      />
    </>
  );
}
