// Overview (P1-10, §13.2): submit-URL control, filter bar, one table row per
// Unit Group, row click opens the detail Drawer (P1-11). Bulk actions (m6),
// the Archived view (m7), and the column picker (m11) live here too.
import {
  Alert,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Menu,
  Modal,
  Paper,
  SegmentedControl,
  Stack,
  Text,
} from "@mantine/core";
import { useLocalStorage } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconArchive, IconArrowsLeftRight, IconChevronDown, IconHome } from "@tabler/icons-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { resolveSettings } from "../../lib/contracts";
import { sentenceCase } from "../../lib/text";
import { useCurrentMember } from "../collaboration/api";
import { useHunt, usePublishSharedFilters, useSharedFilters } from "../hunts/api";
import { usePatchListingStatus, usePatchUnitGroupState } from "./api";
import { useListings, useUnitGroupStates } from "./api";
import { ArchivedListings } from "./ArchivedListings";
import { COMPARE_LIMIT, rowEntry, useCompareSet } from "./compareSet";
import { ListingDetailDrawer, type DrawerSelection } from "./ListingDetailDrawer";
import { OverviewFilterBar } from "./OverviewFilterBar";
import {
  DEFAULT_OVERVIEW_COLUMNS,
  OverviewTable,
  rowKey,
  TableColumnsMenu,
  TableDensityMenu,
  type OverviewColumnKey,
  type TableDensity,
} from "./OverviewTable";
import {
  applyOverviewFilters,
  buildRows,
  DEFAULT_OVERVIEW_FILTERS,
  hasActiveFilters,
  sanitizeFilterState,
  sortRows,
  type OverviewFilterState,
  type SortKey,
  type SortState,
} from "./overviewRows";
import { INTEREST_STATUSES, type InterestStatus } from "./types";
import { SubmitUrlControl } from "./SubmitUrlControl";

/** Listings to archive (single row action or bulk), driving the confirm modal. */
interface ArchiveTarget {
  listingIds: string[];
  label: string;
}

export function OverviewPage() {
  const { huntId = "" } = useParams();
  const { data: hunt } = useHunt(huntId);
  const { data: listings, isLoading, error } = useListings(huntId);
  const { data: unitGroupStates = [] } = useUnitGroupStates(huntId);
  const patchListingStatus = usePatchListingStatus(huntId);
  const patchState = usePatchUnitGroupState(huntId);
  const compare = useCompareSet(huntId);

  const [filters, setFilters] = useState<OverviewFilterState>(DEFAULT_OVERVIEW_FILTERS);
  const [sort, setSort] = useState<SortState>({ key: "score", dir: "desc" });
  const [view, setView] = useState<"active" | "archived">("active");
  const [selected, setSelected] = useState<Set<string>>(new Set());

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
  const canCurate = canPublish;
  const onPublish = (next: OverviewFilterState) =>
    publishFilters.mutate({ ...next }, {
      onSuccess: () =>
        notifications.show({
          message: hasActiveFilters(next)
            ? "Filters applied hunt-wide — members start from this view."
            : "Hunt-wide filters cleared.",
        }),
    });
  // View preferences, not hunt data — persist per browser.
  const [density, setDensity] = useLocalStorage<TableDensity>({
    key: "manzil:overview-density",
    defaultValue: "normal",
  });
  const [columns, setColumns] = useLocalStorage<OverviewColumnKey[]>({
    key: "manzil:overview-columns",
    defaultValue: DEFAULT_OVERVIEW_COLUMNS,
  });
  const [selectedRow, setSelectedRow] = useState<DrawerSelection | null>(null);
  const [drawerOpened, setDrawerOpened] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<ArchiveTarget | null>(null);

  const onSort = (key: SortKey) => {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "desc" ? "asc" : "desc" }
        : { key, dir: key === "name" || key === "available" ? "asc" : "desc" },
    );
  };

  const allRows = buildRows(listings ?? [], unitGroupStates);
  const rows = sortRows(applyOverviewFilters(allRows, filters), sort);
  const cities = [...new Set((listings ?? []).map((listing) => listing.property.city ?? "Unknown"))]
    .sort((a, b) => a.localeCompare(b));

  // Bulk selection (m6) — only selections still visible under the current
  // filters count; hidden-but-selected keys are inert until they reappear.
  const selectedRows = rows.filter((row) => selected.has(rowKey(row)));
  const toggleRow = (key: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const toggleAll = () => {
    const keys = rows.map(rowKey);
    setSelected((prev) =>
      keys.every((key) => prev.has(key)) ? new Set() : new Set(keys),
    );
  };
  const clearSelection = () => setSelected(new Set());

  const bulkSetStatus = async (status: InterestStatus | null) => {
    const targets = selectedRows.filter((row) => row.group !== null);
    for (const row of targets) {
      await patchState.mutateAsync({
        listingId: row.listing.id,
        unitGroupKey: row.group!.key,
        interest_status: status,
        visited: row.state?.visited ?? false,
      });
    }
    notifications.show({
      message: `${targets.length} row${targets.length === 1 ? "" : "s"} set to ${
        status === null ? "undecided" : sentenceCase(status).toLowerCase()
      }.`,
    });
    clearSelection();
  };

  const bulkSendToCompare = () => {
    const entries = selectedRows
      .map(rowEntry)
      .filter((entry): entry is NonNullable<typeof entry> => entry !== null);
    const room = COMPARE_LIMIT - compare.entries.length;
    compare.addMany(entries);
    notifications.show({
      message:
        entries.length > room
          ? `Compare holds ${COMPARE_LIMIT} — added the first ${Math.max(0, room)}.`
          : "Sent to Compare.",
    });
    clearSelection();
  };

  const bulkArchive = () => {
    const ids = [...new Set(selectedRows.map((row) => row.listing.id))];
    setArchiveTarget({
      listingIds: ids,
      label: ids.length === 1
        ? selectedRows[0].listing.property.name
        : `${ids.length} listings`,
    });
  };

  const confirmArchive = async () => {
    if (!archiveTarget) return;
    for (const listingId of archiveTarget.listingIds) {
      await patchListingStatus.mutateAsync({ listingId, status: "archived" });
    }
    notifications.show({
      message: `${archiveTarget.label} archived — restore from the Archived view.`,
    });
    setArchiveTarget(null);
    clearSelection();
  };

  return (
    <Stack gap="lg">
      <PageHeader title="Overview" description="All unit groups in this hunt" />

      <Group justify="space-between" align="flex-end" wrap="wrap" gap="md">
        {hunt && (
          <SubmitUrlControl
            huntId={huntId}
            defaultPolicy={resolveSettings(hunt.settings).default_source_policy}
            listings={listings ?? []}
          />
        )}
      </Group>

      <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm">
        <div style={{ flex: 1, minWidth: 0 }}>
          {view === "active" && (
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
          )}
        </div>
        <Group gap="xs" wrap="nowrap">
          <SegmentedControl
            size="xs"
            value={view}
            onChange={(next) => setView(next as "active" | "archived")}
            data={[
              { value: "active", label: "Active" },
              { value: "archived", label: "Archived" },
            ]}
          />
          <TableColumnsMenu columns={columns} onChange={setColumns} />
          <TableDensityMenu density={density} onChange={setDensity} />
        </Group>
      </Group>

      {view === "archived" && <ArchivedListings huntId={huntId} />}

      {view === "active" && isLoading && (
        <Center py="xl">
          <Stack align="center" gap="xs">
            <Loader />
            <Text size="sm" c="dimmed">
              Fetching your hunt…
            </Text>
          </Stack>
        </Center>
      )}
      {view === "active" && error && (
        <Alert color="red" title="Couldn't load listings">
          {error.message} — try reloading the page.
        </Alert>
      )}
      {view === "active" && !isLoading && !error && rows.length === 0 && (
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
      {view === "active" && selectedRows.length > 0 && (
        <Paper withBorder px="md" py="xs">
          <Group gap="sm" wrap="wrap">
            <Text size="sm" fw={600}>
              {selectedRows.length} selected
            </Text>
            <Menu position="bottom-start" withinPortal>
              <Menu.Target>
                <Button
                  variant="light"
                  size="xs"
                  disabled={!canCurate || patchState.isPending}
                  rightSection={<IconChevronDown size={14} stroke={1.5} />}
                >
                  Set status
                </Button>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item onClick={() => void bulkSetStatus(null)}>Undecided</Menu.Item>
                {INTEREST_STATUSES.map((status) => (
                  <Menu.Item key={status} onClick={() => void bulkSetStatus(status)}>
                    {sentenceCase(status)}
                  </Menu.Item>
                ))}
              </Menu.Dropdown>
            </Menu>
            <Button
              variant="light"
              size="xs"
              leftSection={<IconArrowsLeftRight size={14} stroke={1.5} />}
              onClick={bulkSendToCompare}
            >
              Send to Compare
            </Button>
            <Button
              variant="light"
              color="red"
              size="xs"
              leftSection={<IconArchive size={14} stroke={1.5} />}
              onClick={bulkArchive}
            >
              Archive
            </Button>
            <Button variant="subtle" size="xs" onClick={clearSelection}>
              Clear selection
            </Button>
          </Group>
        </Paper>
      )}
      {view === "active" && rows.length > 0 && (
        <OverviewTable
          huntId={huntId}
          rows={rows}
          sort={sort}
          density={density}
          columns={columns}
          selectedKeys={selected}
          onToggleRow={toggleRow}
          onToggleAll={toggleAll}
          onSort={onSort}
          onOpen={(row) => {
            setSelectedRow({ listingId: row.listing.id, groupKey: row.group?.key ?? null });
            setDrawerOpened(true);
          }}
          onArchive={(row) =>
            setArchiveTarget({ listingIds: [row.listing.id], label: row.listing.property.name })
          }
        />
      )}

      <ListingDetailDrawer
        huntId={huntId}
        selection={selectedRow}
        opened={drawerOpened}
        onClose={() => setDrawerOpened(false)}
        onExited={() => setSelectedRow(null)}
      />

      <Modal
        opened={archiveTarget !== null}
        onClose={() => setArchiveTarget(null)}
        title="Archive listing?"
      >
        <Stack>
          <Text size="sm">
            Hides <Text span fw={600}>{archiveTarget?.label}</Text> — every unit group, score,
            override, and comment — from the Overview. Nothing is deleted; restore any time from
            the Archived view.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setArchiveTarget(null)}>
              Cancel
            </Button>
            <Button
              color="red"
              loading={patchListingStatus.isPending}
              onClick={() => void confirmArchive()}
            >
              Archive
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
