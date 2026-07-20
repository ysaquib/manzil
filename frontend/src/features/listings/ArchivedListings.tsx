// Archived-listings view (m7, §13.2): the `status = archived` rows the active
// Overview hides — archiving is the app's soft delete, so this is where a
// wrong archive gets undone. One row per Listing (unit groups don't matter
// for restore). Restore is Owner-only server-side, like archive.
import { Alert, Button, Card, Center, Loader, Stack, Table, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArchive, IconRestore } from "@tabler/icons-react";

import { ApiError } from "../../lib/apiClient";
import { useArchivedListings, usePatchListingStatus } from "./api";

export function ArchivedListings({ huntId }: { huntId: string }) {
  const { data: listings, isLoading, error } = useArchivedListings(huntId, true);
  const patchStatus = usePatchListingStatus(huntId);

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
              <Text size="sm">{listing.property.city ?? "—"}</Text>
            </Table.Td>
            <Table.Td width={120}>
              <Button
                variant="light"
                size="xs"
                leftSection={<IconRestore size={14} stroke={1.5} />}
                loading={patchStatus.isPending}
                onClick={() => restore(listing.id, listing.property.name)}
              >
                Restore
              </Button>
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
