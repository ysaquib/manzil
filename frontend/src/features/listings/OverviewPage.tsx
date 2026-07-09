// Overview (P1-10, §13.2): submit-URL control, `hide score < N` filter, one
// table row per Unit Group, row click opens the detail Drawer (P1-11).
import {
  Alert,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Modal,
  NumberInput,
  Stack,
  Text,
} from "@mantine/core";
import { IconHome } from "@tabler/icons-react";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { resolveSettings } from "../../lib/contracts";
import { useHunt } from "../hunts/api";
import { useDeleteListing, useListings } from "./api";
import { ListingDetailDrawer } from "./ListingDetailDrawer";
import { OverviewTable } from "./OverviewTable";
import {
  buildRows,
  filterRows,
  sortRows,
  type OverviewRow,
  type SortKey,
  type SortState,
} from "./overviewRows";
import { SubmitUrlControl } from "./SubmitUrlControl";

export function OverviewPage() {
  const { huntId = "" } = useParams();
  const { data: hunt } = useHunt(huntId);
  const { data: listings, isLoading, error } = useListings(huntId);
  const deleteListing = useDeleteListing(huntId);

  const [minScore, setMinScore] = useState<number | null>(null);
  const [sort, setSort] = useState<SortState>({ key: "score", dir: "desc" });
  const [selected, setSelected] = useState<OverviewRow | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<OverviewRow | null>(null);

  const onSort = (key: SortKey) =>
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "desc" ? "asc" : "desc" }
        : { key, dir: key === "name" ? "asc" : "desc" },
    );

  const rows = sortRows(filterRows(buildRows(listings ?? []), minScore), sort);

  return (
    <Stack gap="lg">
      <PageHeader title="Overview" description="All unit groups in this hunt" />

      <Group justify="space-between" align="flex-end" wrap="wrap" gap="md">
        {hunt && (
          <SubmitUrlControl
            huntId={huntId}
            defaultPolicy={resolveSettings(hunt.settings).default_source_policy}
          />
        )}
        <NumberInput
          label="Hide score below"
          placeholder="off"
          value={minScore ?? ""}
          onChange={(next) => setMinScore(typeof next === "number" ? next : null)}
          min={0}
          max={15}
          w={140}
          size="xs"
          styles={{ label: { fontWeight: 400, color: "var(--mantine-color-dimmed)" } }}
        />
      </Group>

      {isLoading && (
        <Center py="xl">
          <Loader />
        </Center>
      )}
      {error && (
        <Alert color="red" title="Couldn't load listings">
          {error.message}
        </Alert>
      )}
      {!isLoading && !error && rows.length === 0 && (
        <Card py="xl">
          <Stack align="center" gap="sm">
            <IconHome size={32} stroke={1.5} color="var(--mantine-color-dimmed)" />
            <Text ta="center" c="dimmed">
              {(listings ?? []).length === 0
                ? "No listings yet — paste a listing URL above to start."
                : "Every listing is hidden by the score filter."}
            </Text>
          </Stack>
        </Card>
      )}
      {rows.length > 0 && (
        <OverviewTable
          rows={rows}
          sort={sort}
          onSort={onSort}
          onOpen={setSelected}
          onDelete={setDeleteTarget}
        />
      )}

      {selected && (
        <ListingDetailDrawer
          huntId={huntId}
          row={selected}
          opened
          onClose={() => setSelected(null)}
        />
      )}

      <Modal
        opened={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title="Delete listing?"
      >
        <Stack>
          <Text size="sm">
            Removes <Text span fw={600}>{deleteTarget?.listing.property.name}</Text> — every unit
            group, score, override, and comment for it in this hunt.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              color="red"
              loading={deleteListing.isPending}
              onClick={() =>
                deleteTarget &&
                deleteListing.mutate(deleteTarget.listing.id, {
                  onSettled: () => setDeleteTarget(null),
                })
              }
            >
              Delete
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
