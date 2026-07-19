// Overview (P1-10, §13.2): submit-URL control, filter bar, one table row per
// Unit Group, row click opens the detail Drawer (P1-11).
import {
  Alert,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
} from "@mantine/core";
import { useLocalStorage } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconHome } from "@tabler/icons-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { resolveSettings } from "../../lib/contracts";
import { useCurrentMember } from "../collaboration/api";
import { useHunt, usePublishSharedFilters, useSharedFilters } from "../hunts/api";
import { useDeleteListing, useListings, useUnitGroupStates } from "./api";
import { ListingDetailDrawer, type DrawerSelection } from "./ListingDetailDrawer";
import { OverviewFilterBar } from "./OverviewFilterBar";
import { OverviewTable, TableDensityMenu, type TableDensity } from "./OverviewTable";
import {
  applyOverviewFilters,
  buildRows,
  DEFAULT_OVERVIEW_FILTERS,
  hasActiveFilters,
  sanitizeFilterState,
  sortRows,
  type OverviewRow,
  type OverviewFilterState,
  type SortKey,
  type SortState,
} from "./overviewRows";
import { SubmitUrlControl } from "./SubmitUrlControl";

export function OverviewPage() {
  const { huntId = "" } = useParams();
  const { data: hunt } = useHunt(huntId);
  const { data: listings, isLoading, error } = useListings(huntId);
  const { data: unitGroupStates = [] } = useUnitGroupStates(huntId);
  const deleteListing = useDeleteListing(huntId);

  const [filters, setFilters] = useState<OverviewFilterState>(DEFAULT_OVERVIEW_FILTERS);
  const [sort, setSort] = useState<SortState>({ key: "score", dir: "desc" });

  // Hunt-wide filters (§13.2, §20 2026-07-19): the published set seeds the
  // local state once per mount — after that the member deviates freely.
  const { data: sharedRow } = useSharedFilters(huntId);
  const publishFilters = usePublishSharedFilters(huntId);
  const { data: currentMember } = useCurrentMember(huntId);
  const sharedFilters = useMemo(
    () => (sharedRow ? sanitizeFilterState(sharedRow.filters) : null),
    [sharedRow],
  );
  const touchedRef = useRef(false);
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current || sharedFilters === null) return;
    seededRef.current = true;
    if (hasActiveFilters(sharedFilters) && !touchedRef.current) setFilters(sharedFilters);
  }, [sharedFilters]);
  const onFiltersChange = (next: OverviewFilterState) => {
    touchedRef.current = true;
    setFilters(next);
  };
  const canPublish = currentMember?.role === "owner" || currentMember?.role === "curator";
  const onPublish = (next: OverviewFilterState) =>
    publishFilters.mutate({ ...next }, {
      onSuccess: () =>
        notifications.show({
          message: hasActiveFilters(next)
            ? "Filters applied hunt-wide — members start from this view."
            : "Hunt-wide filters cleared.",
        }),
    });
  // View preference, not hunt data — persists per browser.
  const [density, setDensity] = useLocalStorage<TableDensity>({
    key: "manzil:overview-density",
    defaultValue: "normal",
  });
  const [selected, setSelected] = useState<DrawerSelection | null>(null);
  const [drawerOpened, setDrawerOpened] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<OverviewRow | null>(null);

  const onSort = (key: SortKey) => {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "desc" ? "asc" : "desc" }
        : { key, dir: key === "name" ? "asc" : "desc" },
    );
  };

  const allRows = buildRows(listings ?? [], unitGroupStates);
  const rows = sortRows(applyOverviewFilters(allRows, filters), sort);
  const cities = [...new Set((listings ?? []).map((listing) => listing.property.city ?? "Unknown"))]
    .sort((a, b) => a.localeCompare(b));

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
      </Group>

      <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm">
        <div style={{ flex: 1, minWidth: 0 }}>
          <OverviewFilterBar
            filters={filters}
            onChange={onFiltersChange}
            cities={cities}
            visibleCount={rows.length}
            totalCount={allRows.length}
            sharedFilters={sharedFilters}
            canPublish={canPublish}
            onPublish={onPublish}
            publishPending={publishFilters.isPending}
          />
        </div>
        <TableDensityMenu density={density} onChange={setDensity} />
      </Group>

      {isLoading && (
        <Center py="xl">
          <Stack align="center" gap="xs">
            <Loader />
            <Text size="sm" c="dimmed">
              Fetching your hunt…
            </Text>
          </Stack>
        </Center>
      )}
      {error && (
        <Alert color="red" title="Couldn't load listings">
          {error.message} — try reloading the page.
        </Alert>
      )}
      {!isLoading && !error && rows.length === 0 && (
        <Card py="xl">
          <Stack align="center" gap="sm">
            <IconHome size={32} stroke={1.5} color="var(--mantine-color-dimmed)" />
            <Text ta="center" c="dimmed">
              {allRows.length === 0
                ? "Nothing here yet. Paste a listing URL above and Manzil will take it from there."
                : hasActiveFilters(filters)
                  ? "Every listing is hidden by your filters. Clear or loosen them to bring rows back."
                  : "No listings match the current view."}
            </Text>
          </Stack>
        </Card>
      )}
      {rows.length > 0 && (
        <OverviewTable
          huntId={huntId}
          rows={rows}
          sort={sort}
          density={density}
          onSort={onSort}
          onOpen={(row) => {
            setSelected({ listingId: row.listing.id, groupKey: row.group?.key ?? null });
            setDrawerOpened(true);
          }}
          onDelete={setDeleteTarget}
        />
      )}

      <ListingDetailDrawer
        huntId={huntId}
        selection={selected}
        opened={drawerOpened}
        onClose={() => setDrawerOpened(false)}
        onExited={() => setSelected(null)}
      />

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
