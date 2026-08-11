// Overview (P1-10, §13.2): submit-URL control, filter bar, one table row per
// Unit Group, row click opens the detail Drawer (P1-11). Bulk actions (m6),
// the Archived view (m7), and the column picker (m11) live here too.
import {
  Alert,
  Box,
  Button,
  Card,
  Center,
  Divider,
  Group,
  Loader,
  Menu,
  Modal,
  Paper,
  SegmentedControl,
  Stack,
  Text,
} from "@mantine/core";
import { useLocalStorage, useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconArchive, IconArrowsLeftRight, IconChevronDown, IconHome } from "@tabler/icons-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { TablePagination, usePagedRows } from "../../components/TablePagination";
import { useAnswerCheckpoint, useJobs } from "../jobs/api";
import { useVisitUnitGroupScores, visitScoreKey } from "../visits/api";
import { jobsByListing, rowPipelineState, type RowPipeline } from "./rowState";
import { OverviewRowList } from "./OverviewRowList";
import { resolveSettings } from "../../lib/contracts";
import { sentenceCase } from "../../lib/text";
import { useHunt } from "../hunts/api";
import { useHuntAccess } from "../hunts/access";
import { isDemo } from "../../lib/demo";
import { useGhostMode } from "../admin/useGhostMode";
import { useCurrentMember } from "../collaboration/api";
import { usePatchListingStatus, usePatchUnitGroupState } from "./api";
import {
  useListings,
  useRefreshStatuses,
  useUnitGroupStates,
} from "./api";
import { ArchivedListings } from "./ArchivedListings";
import { COMPARE_LIMIT, rowEntry, useCompareSet } from "./compareSet";
import { ListingDetailDrawer } from "./ListingDetailDrawer";
import { useDrawerRoute } from "./drawerRoute";
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
  analyzeOverviewFilters,
  buildRows,
  hasActiveFilters,
  sortRows,
  type OverviewRow,
  type SortKey,
  type SortState,
} from "./overviewRows";
import { useOverviewFilters } from "./filterState";
import { propertyLocationLabel } from "./locality";
import { INTEREST_STATUSES, type InterestStatus } from "./types";
import { SubmitUrlControl } from "./SubmitUrlControl";
import { statusesByListing } from "./staleness";
import { useHuntStatistics } from "../statistics/api";

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
  const { data: refreshStatuses = [] } = useRefreshStatuses(huntId);
  const patchListingStatus = usePatchListingStatus(huntId);
  const patchState = usePatchUnitGroupState(huntId);
  const compare = useCompareSet(huntId);
  const { isGhost } = useGhostMode(huntId);
  const { data: currentMember } = useCurrentMember(huntId);
  const access = useHuntAccess(huntId);
  const statistics = useHuntStatistics(huntId, 30, !isDemo());
  const canManageListings = access.canMutate && (isGhost === true || currentMember?.role === "owner");

  const [sort, setSort] = useState<SortState>({ key: "score", dir: "desc" });
  const [view, setView] = useState<"active" | "archived">("active");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Filters (incl. the hunt-wide seed, §13.2 / §20 2026-07-19) are hunt-scoped
  // context now, shared with the Map view (§20 2026-07-26).
  const {
    filters,
    setFilters: onFiltersChange,
    sharedFilters,
    canPublish,
    publish: onPublish,
    publishPending,
  } = useOverviewFilters();
  const canCurate = access.canMutate && canPublish;
  // View preferences, not hunt data — persist per browser.
  const [density, setDensity] = useLocalStorage<TableDensity>({
    key: "manzil:overview-density",
    defaultValue: "normal",
  });
  // The Visit roll-up, indexed the way a row looks it up (VC-8).
  const { data: visitScores = [] } = useVisitUnitGroupScores(huntId);
  const visitScoreIndex = useMemo(
    () => new Map(visitScores.map((entry) => [
      visitScoreKey(entry.hunt_listing_id, entry.unit_group_key),
      entry,
    ])),
    [visitScores],
  );

  const [columns, setColumns] = useLocalStorage<OverviewColumnKey[]>({
    // v2: the column set gained `rent` in the 2026-07-26 redesign; a stored v1
    // array has no entry for it and would render the table without Rent.
    key: "manzil:overview-columns-v2",
    defaultValue: DEFAULT_OVERVIEW_COLUMNS,
  });
  // Drawer state is URL state (P3-16): refreshing reopens it, and the link is
  // shareable with anyone who can read the hunt.
  const drawer = useDrawerRoute();
  const [archiveTarget, setArchiveTarget] = useState<ArchiveTarget | null>(null);

  // Below `sm` the table becomes a row list: a <table> has a minimum width the
  // page cannot escape, and UI_DESIGN §5 forbids horizontal page scroll.
  const isCompact = useMediaQuery("(max-width: 48em)") ?? false;

  const openDrawer = (row: OverviewRow) =>
    drawer.open(row.listing.id, row.group?.key ?? null);
  const archiveRow = (row: OverviewRow) =>
    setArchiveTarget({ listingIds: [row.listing.id], label: row.listing.property.name });

  const onSort = (key: SortKey) => {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "desc" ? "asc" : "desc" }
        : { key, dir: key === "name" || key === "available" ? "asc" : "desc" },
    );
  };

  const allRows = buildRows(listings ?? [], unitGroupStates);
  const filterResult = analyzeOverviewFilters(allRows, filters);
  const rows = sortRows(filterResult.rows, sort);
  // Paged *after* sorting and filtering, so page 1 is the top of the hunt by
  // whatever the viewer sorted on rather than an arbitrary window.
  const paged = usePagedRows(rows, "overview");
  const staleClassesByListing = useMemo(
    () => statusesByListing(
      refreshStatuses,
      Date.now(),
      (listings ?? []).map((listing) => listing.id),
    ),
    [refreshStatuses, listings],
  );

  // Pipeline state per row (UI Decision Log 2026-07-26): a row still being
  // fetched, or whose last run failed, says so and hands off to Tasks.
  const { data: jobs = [] } = useJobs(huntId);
  const answerCheckpoint = useAnswerCheckpoint(huntId);
  const pipeline = useMemo(() => {
    const byListing = jobsByListing(jobs);
    const map = new Map<string, RowPipeline>();
    for (const row of allRows) {
      const state = rowPipelineState(row, byListing);
      if (state) map.set(rowKey(row), state);
    }
    return map;
  }, [jobs, allRows]);
  const autoResolvedListingIds = useMemo(
    () =>
      new Set(
        jobs.flatMap((job) =>
          job.hunt_listing_id &&
          job.auto_resolved_checkpoint &&
          !job.auto_resolved_checkpoint.corrected_at
            ? [job.hunt_listing_id]
            : [],
        ),
      ),
    [jobs],
  );
  const cities = [...new Set((listings ?? []).map((listing) => propertyLocationLabel(listing.property)))]
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
  // Select-all is the header checkbox above a page of rows, so it means "this
  // page" — not a silent selection of 4,000 rows nobody has looked at. The bulk
  // bar still counts selections made on other pages.
  const toggleAll = () => {
    const keys = paged.items.map(rowKey);
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

      {(statistics.data?.summary.deleted_cost_usd ?? 0) > 0 && (
        <Alert color="gray" variant="light">
          Total spend includes ${statistics.data!.summary.deleted_cost_usd.toFixed(2)} from deleted
          Jobs. <Text component={Link} to={`/h/${huntId}/statistics`} span inherit td="underline">See Statistics</Text>
        </Alert>
      )}

      {hunt && access.canMutate && (
        <SubmitUrlControl
          huntId={huntId}
          defaultPolicy={resolveSettings(hunt.settings).default_source_policy}
          listings={listings ?? []}
        />
      )}

      {/* Search + Filters read as one control; the view options group into a
          single bordered cluster instead of floating loose (§20 2026-07-26). */}
      <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
        <Box style={{ flex: 1, minWidth: 260 }}>
          {view === "active" && (
            <OverviewFilterBar
              filters={filters}
              onChange={onFiltersChange}
              cities={cities}
              visibleCount={rows.length}
              totalCount={allRows.length}
              manualPinAlternateMatchCount={filterResult.manualPinAlternateMatchCount}
              sharedFilters={sharedFilters}
              canPublish={access.canMutate && canPublish}
              onPublish={onPublish}
              publishPending={publishPending}
            />
          )}
        </Box>
        <Paper withBorder p={3} radius="md">
          <Group gap={2} wrap="nowrap">
            {/* DM-9: archived Demo-Hunt Listings are the published replay slate,
                so opening this view would spoil what each submission reveals.
                Hiding the toggle is UX, not a security boundary -- the rows are
                genuinely there and RLS scopes them like every other Listing. */}
            {!isDemo() && (
              <SegmentedControl
                size="xs"
                variant="subtle"
                value={view}
                onChange={(next) => setView(next as "active" | "archived")}
                data={[
                  { value: "active", label: "Active" },
                  { value: "archived", label: "Archived" },
                ]}
              />
            )}
            {!isCompact && (
              <>
                <Divider orientation="vertical" my={4} />
                <TableColumnsMenu columns={columns} onChange={setColumns} />
                <TableDensityMenu density={density} onChange={setDensity} />
              </>
            )}
          </Group>
        </Paper>
      </Group>

      {view === "archived" && (
        <ArchivedListings huntId={huntId} canManage={canManageListings} />
      )}

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
              disabled={!access.canMutate}
            >
              Send to Compare
            </Button>
            {canManageListings && (
              <Button
                variant="light"
                color="red"
                size="xs"
                leftSection={<IconArchive size={14} stroke={1.5} />}
                onClick={bulkArchive}
              >
                Archive
              </Button>
            )}
            <Button variant="subtle" size="xs" onClick={clearSelection}>
              Clear selection
            </Button>
          </Group>
        </Paper>
      )}
      {view === "active" && rows.length > 0 &&
        (isCompact ? (
          <OverviewRowList
            huntId={huntId}
            rows={paged.items}
            pipeline={pipeline}
            staleClassesByListing={staleClassesByListing}
            autoResolvedListingIds={autoResolvedListingIds}
            onOpen={openDrawer}
            onArchive={canManageListings ? archiveRow : undefined}
          />
        ) : (
          <OverviewTable
            huntId={huntId}
            rows={paged.items}
            sort={sort}
            density={density}
            columns={columns}
            pipeline={pipeline}
            staleClassesByListing={staleClassesByListing}
            autoResolvedListingIds={autoResolvedListingIds}
            selectedKeys={selected}
            onToggleRow={toggleRow}
            onToggleAll={toggleAll}
            onSort={onSort}
            onOpen={openDrawer}
            onArchive={canManageListings ? archiveRow : undefined}
            visitScores={visitScoreIndex}
          />
        ))}
      {view === "active" && rows.length > 0 && (
        <Paper withBorder radius="md">
          <TablePagination state={paged} noun="unit groups" />
        </Paper>
      )}

      <ListingDetailDrawer
        huntId={huntId}
        selection={drawer.renderSelection}
        opened={drawer.opened}
        onClose={drawer.close}
        onExited={drawer.onExited}
        isGhost={isGhost === true}
        filters={filters}
        jobs={jobs}
        answeringCheckpoint={answerCheckpoint.isPending}
        onAnswerCheckpoint={(jobId, choice, text) =>
          answerCheckpoint.mutate({ jobId, choice, text })
        }
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
