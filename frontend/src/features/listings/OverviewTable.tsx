// Overview table (P1-10, §13.2; redesigned UI Decision Log 2026-07-26): plain
// Mantine Table over the tested pure row logic in overviewRows.ts. One row per
// Unit Group; the score cell shows the group's manual pin, filter-selected
// Floor Plan, or ordinary best-scoring plan (§9.4).
//
// Layout decisions:
// - One fact per column, so every value stays independently sortable, grouped
//   under a band (FIT · IDENTITY · UNIT · MONEY · TIMING · PLACE · CURATION ·
//   PEOPLE) with a hairline opening each group.
// - Selection, score and property are pinned; everything else scrolls inside
//   the table's own container, so the page never scrolls sideways (UI_DESIGN §5).
// - The row menu lives inside the pinned property cell rather than a right-hand
//   rail: it costs no column and is reachable at any scroll position.
// - A row still being fetched, or whose last run failed, shows that in the
//   marker slot and hands off to Tasks instead of opening an empty drawer.
import {
  ActionIcon,
  Anchor,
  Box,
  Checkbox,
  Group,
  Menu,
  Table,
  Text,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconArchive,
  IconArrowsLeftRight,
  IconBaselineDensityLarge,
  IconBaselineDensityMedium,
  IconBaselineDensitySmall,
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconChevronUp,
  IconColumns,
  IconCopy,
  IconDotsVertical,
  IconExternalLink,
  IconEye,
  IconRefresh,
} from "@tabler/icons-react";
import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { AllInCell } from "./AllInCost";
import {
  AutoResolvedBadge,
  SingleSourceBadge,
  StaleBadge,
} from "../../components/badges/ListingBadges";
import { COMPARE_LIMIT, rowEntry, useCompareSet } from "./compareSet";
import { CurationCell } from "./StatusChip";
import { propertyLocationLabel } from "./locality";
import { RatingSummary } from "../collaboration/RatingSummary";
import { RowMarker } from "./RowMarker";
import { ScoreCell } from "./ScoreCell";
import { visitScoreKey } from "../visits/api";
import { VisitScoreCell } from "../visits/VisitScoreCell";
import type { VisitUnitGroupScore } from "../visits/types";
import { useComments, useCurrentMember, useHuntContributors, useMembers, useRatings } from "../collaboration/api";
import { usePatchUnitGroupState, useRefreshListing } from "./api";
import {
  pipelineErrorWasTruncated,
  pipelineFailureLabel,
  type RowPipeline,
} from "./rowState";
import type { InterestStatus } from "./types";
import type { RefreshClass } from "./types";
import {
  allInValue,
  earliestAvailability,
  formatRange,
  rowAvailability,
  rowComposition,
  type OverviewRow,
  type SortKey,
  type SortState,
} from "./overviewRows";
import { sentenceCase } from "../../lib/text";
import { useGhostMode } from "../admin/useGhostMode";

import classes from "./OverviewTable.module.css";

function SortHeader({
  label,
  sortKey,
  sort,
  onSort,
}: {
  label: string;
  sortKey: SortKey;
  sort: SortState;
  onSort: (key: SortKey) => void;
}) {
  const active = sort.key === sortKey;
  const SortIcon = active ? (sort.dir === "asc" ? IconChevronUp : IconChevronDown) : IconChevronRight;
  return (
    <UnstyledButton onClick={() => onSort(sortKey)} aria-label={`sort by ${label}`}>
      <Group gap={4} wrap="nowrap" className={active ? classes.activeheader : undefined}>
        <Text size="xs" span fw={700}>
          {label}
        </Text>
        <SortIcon size={13} stroke={1.5} />
      </Group>
    </UnstyledButton>
  );
}

// Row density (view options): spacing only — content and type size stay put.
export type TableDensity = "compact" | "normal" | "comfortable";

const DENSITY_SPACING: Record<TableDensity, { vertical: string | number; horizontal: string }> = {
  compact: { vertical: 4, horizontal: "xs" },
  normal: { vertical: "sm", horizontal: "sm" },
  comfortable: { vertical: "lg", horizontal: "md" },
};

const DENSITY_OPTIONS: { value: TableDensity; label: string; icon: typeof IconBaselineDensitySmall }[] = [
  { value: "compact", label: "Compact", icon: IconBaselineDensitySmall },
  { value: "normal", label: "Normal", icon: IconBaselineDensityMedium },
  { value: "comfortable", label: "Comfortable", icon: IconBaselineDensityLarge },
];

export function TableDensityMenu({
  density,
  onChange,
}: {
  density: TableDensity;
  onChange: (next: TableDensity) => void;
}) {
  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <Tooltip label="Row density" openDelay={300}>
          <ActionIcon color="gray" c="dimmed" aria-label="table view options" size="lg">
            <IconBaselineDensityMedium size={16} stroke={1.5} />
          </ActionIcon>
        </Tooltip>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Row density</Menu.Label>
        {DENSITY_OPTIONS.map(({ value, label, icon: Icon }) => (
          <Menu.Item
            key={value}
            leftSection={<Icon size={14} stroke={1.5} />}
            rightSection={density === value ? <IconCheck size={14} stroke={1.5} /> : undefined}
            onClick={() => onChange(value)}
          >
            {label}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}

// Column visibility (m11): the optional columns and their defaults. Score,
// Property and the row menu are always on.
export type OverviewColumnKey =
  | "sqft" | "allIn" | "curation" | "people" | "visit"
  | "city" | "available" | "deposit" | "added" | "rent";

export const COLUMN_OPTIONS: { key: OverviewColumnKey; label: string; defaultVisible: boolean }[] = [
  { key: "sqft", label: "Sqft", defaultVisible: true },
  { key: "allIn", label: "All-In Monthly", defaultVisible: true },
  { key: "rent", label: "Rent", defaultVisible: true },
  { key: "curation", label: "Status", defaultVisible: true },
  { key: "people", label: "People", defaultVisible: true },
  // On by default: a tour is expensive to do and the whole point is that it
  // sits next to Fit where the comparison is unavoidable.
  { key: "visit", label: "Visit", defaultVisible: true },
  { key: "city", label: "City", defaultVisible: false },
  { key: "available", label: "Available", defaultVisible: false },
  { key: "deposit", label: "Deposit", defaultVisible: false },
  { key: "added", label: "Added", defaultVisible: false },
];

export const DEFAULT_OVERVIEW_COLUMNS: OverviewColumnKey[] = COLUMN_OPTIONS.filter(
  (option) => option.defaultVisible,
).map((option) => option.key);

export function TableColumnsMenu({
  columns,
  onChange,
}: {
  columns: OverviewColumnKey[];
  onChange: (next: OverviewColumnKey[]) => void;
}) {
  const toggle = (key: OverviewColumnKey) =>
    onChange(
      columns.includes(key) ? columns.filter((k) => k !== key) : [...columns, key],
    );
  return (
    <Menu position="bottom-end" withinPortal closeOnItemClick={false}>
      <Menu.Target>
        <Tooltip label="Columns" openDelay={300}>
          <ActionIcon color="gray" c="dimmed" aria-label="table columns" size="lg">
            <IconColumns size={16} stroke={1.5} />
          </ActionIcon>
        </Tooltip>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Columns</Menu.Label>
        {COLUMN_OPTIONS.map(({ key, label }) => (
          <Menu.Item
            key={key}
            rightSection={columns.includes(key) ? <IconCheck size={14} stroke={1.5} /> : undefined}
            onClick={() => toggle(key)}
          >
            {label}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}

/** Stable identity for a table row — also the bulk-selection key (m6). */
export const rowKey = (row: OverviewRow) => `${row.listing.id}:${row.group?.key ?? "listing"}`;

// Column groups drive the header band. Only groups with a visible column are
// rendered, and the first visible column of each opens with a hairline.
const GROUPS: { label: string; columns: OverviewColumnKey[] }[] = [
  { label: "Money", columns: ["allIn", "rent", "deposit"] },
  { label: "Timing", columns: ["available", "added"] },
  { label: "Place", columns: ["city"] },
  { label: "Curation", columns: ["curation"] },
  { label: "People", columns: ["people", "visit"] },
];

export interface OverviewTableProps {
  huntId: string;
  rows: OverviewRow[];
  sort: SortState;
  onSort: (key: SortKey) => void;
  onOpen: (row: OverviewRow) => void;
  onArchive?: (row: OverviewRow) => void;
  density?: TableDensity;
  columns?: OverviewColumnKey[];
  /** Pipeline state per row key, from rowState.ts; absent when the row is idle. */
  pipeline?: Map<string, RowPipeline>;
  staleClassesByListing?: Map<string, RefreshClass[]>;
  autoResolvedListingIds?: Set<string>;
  /** Bulk selection (m6): selected row keys; omit to hide the checkbox column. */
  selectedKeys?: Set<string>;
  onToggleRow?: (key: string) => void;
  onToggleAll?: () => void;
  /** Visit roll-up by `visitScoreKey(listingId, unitGroupKey)` (VC-8). */
  visitScores?: Map<string, VisitUnitGroupScore>;
}

function PeopleCell({
  listingId,
  huntId,
  unitGroupKey,
}: {
  listingId: string;
  huntId: string;
  unitGroupKey: string | null;
}) {
  const { data: members = [] } = useMembers(huntId);
  const { data: contributors = [] } = useHuntContributors(huntId);
  const { data: ratings = [] } = useRatings(listingId);
  const { data: comments = [] } = useComments(listingId);
  const rowRatings = ratings.filter((rating) => rating.unit_group_key === unitGroupKey);
  const rowComments = comments.filter(
    (comment) => comment.unit_group_key === null || comment.unit_group_key === unitGroupKey,
  );
  return (
    <RatingSummary
      ratings={rowRatings}
      members={members}
      contributors={contributors}
      commentCount={rowComments.length}
    />
  );
}

function CurationCells({ row, huntId }: { row: OverviewRow; huntId: string }) {
  const { data: currentMember } = useCurrentMember(huntId);
  const { isGhost } = useGhostMode(huntId);
  const patchState = usePatchUnitGroupState(huntId);
  const canCurate = isGhost === true || currentMember?.role === "owner" || currentMember?.role === "curator";
  const group = row.group;
  const visited = row.state?.visited ?? false;
  const save = (interest_status: InterestStatus | null, nextVisited: boolean) => {
    if (!group) return;
    patchState.mutate({
      listingId: row.listing.id,
      unitGroupKey: group.key,
      interest_status,
      visited: nextVisited,
    });
  };
  if (!group) return <Text size="sm" c="dimmed">—</Text>;
  return (
    <CurationCell
      status={row.state?.interest_status ?? null}
      visited={visited}
      disabled={!canCurate || patchState.isPending}
      onStatus={(next) => save(next, visited)}
      onVisited={(next) => save(row.state?.interest_status ?? null, next)}
    />
  );
}

// Per-row actions beyond "open the drawer": jump to the live listing page,
// grab the address/link for sharing, and archive last (soft — the Archived
// view can restore it).
function RowActionsMenu({
  row,
  huntId,
  onOpen,
  onArchive,
}: {
  row: OverviewRow;
  huntId: string;
  onOpen: (row: OverviewRow) => void;
  onArchive?: (row: OverviewRow) => void;
}) {
  const property = row.listing.property;
  const listingUrl = property.official_url ?? property.sources[0]?.url ?? null;
  const compare = useCompareSet(huntId);
  const entry = rowEntry(row);
  const inCompare = compare.has(entry);
  const compareBlocked = entry === null || (compare.isFull && !inCompare);
  const { data: currentMember } = useCurrentMember(huntId);
  const { isGhost } = useGhostMode(huntId);
  const refresh = useRefreshListing(huntId);
  const canRefresh =
    isGhost === true ||
    currentMember?.role === "owner" ||
    currentMember?.user_id === row.listing.added_by;

  const copy = async (label: string, value: string) => {
    await navigator.clipboard.writeText(value);
    notifications.show({ message: `${label} copied`, color: "green", autoClose: 1800 });
  };

  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <ActionIcon
          color="gray"
          c="dimmed"
          size="sm"
          className={classes.rowMenu}
          aria-label="listing actions"
        >
          <IconDotsVertical size={15} stroke={1.5} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item leftSection={<IconEye size={14} stroke={1.5} />} onClick={() => onOpen(row)}>
          Open details
        </Menu.Item>
        <Tooltip
          label={
            entry === null
              ? "Only scored unit groups can be compared"
              : `Compare is full (${COMPARE_LIMIT}) — remove one first`
          }
          openDelay={300}
          disabled={!compareBlocked}
        >
          <Menu.Item
            leftSection={<IconArrowsLeftRight size={14} stroke={1.5} />}
            disabled={compareBlocked}
            onClick={() => entry && compare.toggle(entry)}
          >
            {inCompare ? "Remove from Compare" : "Send to Compare"}
          </Menu.Item>
        </Tooltip>
        {listingUrl && (
          <Menu.Item
            leftSection={<IconExternalLink size={14} stroke={1.5} />}
            onClick={() => window.open(listingUrl, "_blank", "noopener")}
          >
            Open listing page
          </Menu.Item>
        )}
        <Menu.Item
          leftSection={<IconRefresh size={14} stroke={1.5} />}
          disabled={!canRefresh || refresh.isPending}
          onClick={() =>
            refresh.mutate(
              { listingId: row.listing.id },
              {
                onSuccess: () =>
                  notifications.show({
                    message: `${property.name} refresh queued`,
                    color: "green",
                  }),
              },
            )
          }
        >
          Refresh data
        </Menu.Item>
        <Menu.Item
          leftSection={<IconCopy size={14} stroke={1.5} />}
          onClick={() => void copy("Address", property.canonical_address)}
        >
          Copy address
        </Menu.Item>
        {listingUrl && (
          <Menu.Item
            leftSection={<IconCopy size={14} stroke={1.5} />}
            onClick={() => void copy("Listing link", listingUrl)}
          >
            Copy listing link
          </Menu.Item>
        )}
        {onArchive && (
          <>
            <Menu.Divider />
            <Menu.Item
              color="red"
              leftSection={<IconArchive size={14} stroke={1.5} />}
              onClick={() => onArchive(row)}
            >
              Archive listing
            </Menu.Item>
          </>
        )}
      </Menu.Dropdown>
    </Menu>
  );
}

const dateLabel = (iso: string | null) =>
  iso === null ? "—" : new Date(iso.includes("T") ? iso : `${iso}T00:00:00`).toLocaleDateString();

/** What a working/failed row says in place of its address, plus where it goes. */
function PipelineSubline({ huntId, pipeline }: { huntId: string; pipeline: RowPipeline }) {
  const working = pipeline.state === "working";
  const failureDetail = !working && pipeline.detail ? pipeline.detail : null;
  const failureLine = failureDetail ? pipelineFailureLabel(failureDetail) : null;
  const showFullError =
    failureDetail !== null && pipelineErrorWasTruncated(failureDetail);
  return (
    <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
      <Tooltip
        label={failureDetail}
        openDelay={300}
        multiline
        maw={320}
        disabled={!showFullError}
      >
        <Text size="xs" c={working ? "dusky" : "red"} truncate style={{ minWidth: 0 }}>
          {working
            ? `Working${pipeline.detail ? ` · ${sentenceCase(pipeline.detail.toLowerCase())}` : ""}`
            : failureLine}
        </Text>
      </Tooltip>
      <Anchor
        component={Link}
        to={`/h/${huntId}/tasks${working ? "" : "?tab=history"}`}
        size="xs"
        fw={600}
        onClick={(event) => event.stopPropagation()}
        style={{ whiteSpace: "nowrap" }}
      >
        {working ? "View task" : "See history"} ›
      </Anchor>
    </Group>
  );
}

const EM_DASH = <Text size="sm" c="dimmed">—</Text>;

export function OverviewTable({
  huntId,
  rows,
  sort,
  onSort,
  onOpen,
  onArchive,
  density = "normal",
  columns = DEFAULT_OVERVIEW_COLUMNS,
  pipeline,
  staleClassesByListing,
  autoResolvedListingIds,
  selectedKeys,
  onToggleRow,
  onToggleAll,
  visitScores,
}: OverviewTableProps) {
  const spacing = DENSITY_SPACING[density];
  const show = (key: OverviewColumnKey) => columns.includes(key);
  const selectable = selectedKeys !== undefined && onToggleRow !== undefined;
  const allSelected = selectable && rows.length > 0 && rows.every((row) => selectedKeys.has(rowKey(row)));
  const someSelected = selectable && rows.some((row) => selectedKeys.has(rowKey(row)));

  // The pinned columns only cast a shadow while a column is genuinely scrolled
  // underneath them: none at rest, none when every column already fits.
  const wrapRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const sync = () => wrap.toggleAttribute("data-scrolled", wrap.scrollLeft > 0);
    sync();
    wrap.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", sync);
    return () => {
      wrap.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
    };
  }, [columns, rows.length]);

  // Header band: a group appears only when it still has a visible column, and
  // its first visible column opens with the hairline.
  // Unit is a fixed column like score and property, so its group always exists
  // and always opens the band; sqft joins it when enabled.
  const unitGroup = { label: "Unit", columns: ["unit", ...(show("sqft") ? ["sqft"] : [])] };
  const visibleGroups = [
    unitGroup,
    ...GROUPS.map((group) => ({
      label: group.label,
      columns: group.columns.filter(show) as string[],
    })).filter((group) => group.columns.length > 0),
  ];
  const groupStarts = new Set(visibleGroups.map((group) => group.columns[0]));
  const cellClass = (key: string) => (groupStarts.has(key) ? classes.groupStart : undefined);

  const cell = (key: OverviewColumnKey, content: ReactNode) =>
    show(key) ? <Table.Td className={cellClass(key)}>{content}</Table.Td> : null;

  return (
    <Box className={classes.wrap} ref={wrapRef}>
      <Table
        className={classes.table}
        data-selectable={selectable ? "true" : undefined}
        verticalSpacing={spacing.vertical}
        horizontalSpacing={spacing.horizontal}
        withRowBorders={false}
      >
        <Table.Thead>
          <Table.Tr className={classes.bandRow}>
            {selectable && <Table.Th className={`${classes.sticky} ${classes.stickySelect}`} />}
            <Table.Th className={`${classes.sticky} ${classes.stickyScore}`}>Fit</Table.Th>
            <Table.Th className={`${classes.sticky} ${classes.stickyProp}`}>Identity</Table.Th>
            {visibleGroups.map((group) => (
              <Table.Th key={group.label} colSpan={group.columns.length} className={classes.groupStart}>
                {group.label}
              </Table.Th>
            ))}
          </Table.Tr>
          <Table.Tr className={classes.labelRow}>
            {selectable && (
              <Table.Th className={`${classes.sticky} ${classes.stickySelect}`}>
                <Checkbox
                  aria-label="select all rows"
                  checked={allSelected}
                  indeterminate={someSelected && !allSelected}
                  onChange={() => onToggleAll?.()}
                />
              </Table.Th>
            )}
            <Table.Th className={`${classes.sticky} ${classes.stickyScore}`}>
              <SortHeader label="Score" sortKey="score" sort={sort} onSort={onSort} />
            </Table.Th>
            <Table.Th className={`${classes.sticky} ${classes.stickyProp}`}>
              <SortHeader label="Property" sortKey="name" sort={sort} onSort={onSort} />
            </Table.Th>
            <Table.Th className={cellClass("unit")}>Unit</Table.Th>
            {show("sqft") && (
              <Table.Th className={cellClass("sqft")}>
                <SortHeader label="Sqft" sortKey="sqft" sort={sort} onSort={onSort} />
              </Table.Th>
            )}
            {show("allIn") && (
              <Table.Th className={cellClass("allIn")}>
                <SortHeader label="All-In Monthly" sortKey="allIn" sort={sort} onSort={onSort} />
              </Table.Th>
            )}
            {show("rent") && (
              <Table.Th className={cellClass("rent")}>
                <SortHeader label="Rent" sortKey="rent" sort={sort} onSort={onSort} />
              </Table.Th>
            )}
            {show("deposit") && <Table.Th className={cellClass("deposit")}>Deposit</Table.Th>}
            {show("available") && (
              <Table.Th className={cellClass("available")}>
                <SortHeader label="Available" sortKey="available" sort={sort} onSort={onSort} />
              </Table.Th>
            )}
            {show("added") && (
              <Table.Th className={cellClass("added")}>
                <SortHeader label="Added" sortKey="added" sort={sort} onSort={onSort} />
              </Table.Th>
            )}
            {show("city") && <Table.Th className={cellClass("city")}>City</Table.Th>}
            {show("curation") && (
              <Table.Th className={cellClass("curation")}>
                <SortHeader label="Status" sortKey="status" sort={sort} onSort={onSort} />
              </Table.Th>
            )}
            {show("people") && <Table.Th className={cellClass("people")}>People</Table.Th>}
            {show("visit") && <Table.Th className={cellClass("visit")}>Visit</Table.Th>}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => {
            const allIn = allInValue(row);
            const group = row.group;
            const availability = rowAvailability(row);
            const key = rowKey(row);
            const state = pipeline?.get(key) ?? null;
            // A row with nothing of its own yet stands in as a hand-off to
            // Tasks; a scored row that is merely refreshing keeps its values.
            const blank = state?.placeholder ?? false;
            const dimmed = availability === "unavailable" || blank;
            return (
              <Table.Tr
                key={key}
                onClick={() => onOpen(row)}
                style={{ cursor: "pointer", opacity: dimmed && !blank ? 0.55 : 1 }}
              >
                {selectable && (
                  <Table.Td
                    className={`${classes.sticky} ${classes.stickySelect}`}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Checkbox
                      aria-label="select row"
                      checked={selectedKeys.has(key)}
                      onChange={() => onToggleRow?.(key)}
                    />
                  </Table.Td>
                )}
                <Table.Td className={`${classes.sticky} ${classes.stickyScore}`}>
                  {blank ? (
                    EM_DASH
                  ) : group?.displayScore ? (
                    <ScoreCell
                      total={group.displayScore.total}
                      pinned={group.pinnedPlanId !== null}
                      filterSelected={group.filterSelectedPlanId !== null}
                      planName={group.displayPlan.plan_name}
                      planCount={group.scoredPlanCount}
                    />
                  ) : (
                    <Text size="sm" c="dimmed">
                      {availability === "unavailable" ? "No availability" : "Pending"}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td className={`${classes.sticky} ${classes.stickyProp}`}>
                  <Box className={classes.identity}>
                    <RowMarker
                      pipeline={state?.state ?? null}
                      status={row.state?.interest_status ?? null}
                    />
                    <Box className={classes.identityText}>
                      <Group gap="xs" wrap="nowrap">
                        <Text size="sm" fw={600} truncate>
                          {row.listing.property.name}
                        </Text>
                        {row.listing.single_source_reason && !state && (
                          <SingleSourceBadge reason={row.listing.single_source_reason} />
                        )}
                        {autoResolvedListingIds?.has(row.listing.id) && !state && (
                          <AutoResolvedBadge />
                        )}
                        {!state && (
                          <StaleBadge
                            classes={staleClassesByListing?.get(row.listing.id) ?? []}
                          />
                        )}
                      </Group>
                      {state ? (
                        <PipelineSubline huntId={huntId} pipeline={state} />
                      ) : (
                        <Text size="xs" c="dimmed" truncate>
                          {row.listing.property.canonical_address}
                        </Text>
                      )}
                    </Box>
                    <Box onClick={(e) => e.stopPropagation()}>
                      <RowActionsMenu
                        row={row}
                        huntId={huntId}
                        onOpen={onOpen}
                        onArchive={onArchive}
                      />
                    </Box>
                  </Box>
                </Table.Td>

                <Table.Td className={cellClass("unit")}>
                  {blank ? (
                    EM_DASH
                  ) : (
                    <Box>
                      <Text size="sm" lh={1.2}>
                        {group === null
                          ? "—"
                          : `${group.beds === 0 ? "Studio" : `${group.beds} bd`} / ${group.baths} ba`}
                      </Text>
                      {group && group.unitTypes.length > 0 && (
                        <Text size="xs" c="dimmed">
                          {group.unitTypes.map((type) => sentenceCase(type)).join(", ")}
                        </Text>
                      )}
                    </Box>
                  )}
                </Table.Td>
                {cell(
                  "sqft",
                  blank ? EM_DASH : (
                    <Text size="sm" className={classes.figure}>
                      {group === null ? "—" : formatRange(group.sqftMin, group.sqftMax)}
                    </Text>
                  ),
                )}
                {cell(
                  "allIn",
                  blank ? EM_DASH : <AllInCell allIn={allIn} composition={rowComposition(row)} />,
                )}
                {cell(
                  "rent",
                  blank ? EM_DASH : (
                    <Text size="sm" className={classes.figure}>
                      {group === null ? "—" : formatRange(group.rentMin, group.rentMax, "$")}
                    </Text>
                  ),
                )}
                {cell(
                  "deposit",
                  blank ? EM_DASH : (
                    <Text size="sm" className={classes.figure}>
                      {group?.displayPlan.deposit != null
                        ? `$${group.displayPlan.deposit.toLocaleString()}`
                        : "—"}
                    </Text>
                  ),
                )}
                {cell(
                  "available",
                  blank ? EM_DASH : (
                    <Text size="sm" className={classes.figure}>
                      {dateLabel(earliestAvailability(row))}
                    </Text>
                  ),
                )}
                {cell(
                  "added",
                  <Text size="sm" className={classes.figure}>
                    {dateLabel(row.listing.created_at)}
                  </Text>,
                )}
                {cell(
                  "city",
                  blank ? EM_DASH : (
                    <Text size="sm">
                      {propertyLocationLabel(row.listing.property) === "Unknown"
                        ? "—"
                        : propertyLocationLabel(row.listing.property)}
                    </Text>
                  ),
                )}
                {show("curation") && (
                  <Table.Td className={cellClass("curation")} onClick={(e) => e.stopPropagation()}>
                    {blank ? EM_DASH : <CurationCells row={row} huntId={huntId} />}
                  </Table.Td>
                )}
                {cell(
                  "people",
                  blank ? EM_DASH : (
                    <PeopleCell
                      listingId={row.listing.id}
                      huntId={huntId}
                      unitGroupKey={group?.key ?? null}
                    />
                  ),
                )}
                {cell(
                  "visit",
                  blank ? EM_DASH : (
                    <VisitScoreCell
                      entry={visitScores?.get(visitScoreKey(row.listing.id, group?.key ?? null))}
                    />
                  ),
                )}
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Box>
  );
}
