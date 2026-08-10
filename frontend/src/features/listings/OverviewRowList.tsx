// Mobile Overview (UI Decision Log 2026-07-26): the same rows as the desktop
// table, as a list that expands in place.
//
// Collapsed, a row carries only what you decide on — score, property, unit, and
// the all-in monthly figure. The chevron expands to the desktop columns and
// stops there; photos, fees, the score breakdown and notes stay in the drawer,
// which is still what tapping the row itself opens.
import { ActionIcon, Anchor, Box, Button, Collapse, Group, Stack, Text, Tooltip, UnstyledButton } from "@mantine/core";
import {
  IconArchive,
  IconArrowsLeftRight,
  IconChevronDown,
  IconChevronUp,
  IconExternalLink,
} from "@tabler/icons-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { AllInCell } from "./AllInCost";
import { CurationCell } from "./StatusChip";
import { propertyLocationLabel } from "./locality";
import { RatingSummary } from "../collaboration/RatingSummary";
import { RowMarker } from "./RowMarker";
import { rowKey } from "./OverviewTable";
import { ScoreCell } from "./ScoreCell";
import { useComments, useCurrentMember, useMembers, useRatings } from "../collaboration/api";
import { usePatchUnitGroupState } from "./api";
import { rowEntry, useCompareSet } from "./compareSet";
import {
  pipelineErrorWasTruncated,
  pipelineFailureLabel,
  type RowPipeline,
} from "./rowState";
import type { InterestStatus } from "./types";
import {
  allInValue,
  earliestAvailability,
  formatRange,
  rowAvailability,
  rowComposition,
  type OverviewRow,
} from "./overviewRows";
import { sentenceCase } from "../../lib/text";
import {
  AutoResolvedBadge,
  StaleBadge,
} from "../../components/badges/ListingBadges";
import type { RefreshClass } from "./types";
import { useGhostMode } from "../admin/useGhostMode";

import classes from "./OverviewRowList.module.css";

const dateLabel = (iso: string | null) =>
  iso === null ? "—" : new Date(iso.includes("T") ? iso : `${iso}T00:00:00`).toLocaleDateString();

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Box>
      <Text className={classes.statKey}>{label}</Text>
      <Box className={classes.statValue}>{children}</Box>
    </Box>
  );
}

function ExpandedDetail({
  row,
  huntId,
  onArchive,
}: {
  row: OverviewRow;
  huntId: string;
  onArchive?: (row: OverviewRow) => void;
}) {
  const group = row.group;
  const { data: members = [] } = useMembers(huntId);
  const { data: ratings = [] } = useRatings(row.listing.id);
  const { data: comments = [] } = useComments(row.listing.id);
  const { data: currentMember } = useCurrentMember(huntId);
  const { isGhost } = useGhostMode(huntId);
  const patchState = usePatchUnitGroupState(huntId);
  const compare = useCompareSet(huntId);
  const entry = rowEntry(row);
  const canCurate = isGhost === true || currentMember?.role === "owner" || currentMember?.role === "curator";
  const visited = row.state?.visited ?? false;
  const listingUrl = row.listing.property.official_url ?? row.listing.property.sources[0]?.url ?? null;

  const rowRatings = ratings.filter((rating) => rating.unit_group_key === (group?.key ?? null));
  const rowComments = comments.filter(
    (comment) => comment.unit_group_key === null || comment.unit_group_key === (group?.key ?? null),
  );

  const save = (interest_status: InterestStatus | null, nextVisited: boolean) => {
    if (!group) return;
    patchState.mutate({
      listingId: row.listing.id,
      unitGroupKey: group.key,
      interest_status,
      visited: nextVisited,
    });
  };

  return (
    <Box className={classes.more}>
      <Box className={classes.stats}>
        <Stat label="Rent / Month">
          {group === null ? "—" : formatRange(group.rentMin, group.rentMax, "$")}
        </Stat>
        <Stat label="Sqft">{group === null ? "—" : formatRange(group.sqftMin, group.sqftMax)}</Stat>
        <Stat label="Available">{dateLabel(earliestAvailability(row))}</Stat>
        <Stat label="Deposit">
          {group?.displayPlan.deposit != null
            ? `$${group.displayPlan.deposit.toLocaleString()}`
            : "—"}
        </Stat>
        <Stat label="City">
          <Text size="xs" className={classes.statValuePlain}>
            {propertyLocationLabel(row.listing.property) === "Unknown"
              ? "—"
              : propertyLocationLabel(row.listing.property)}
          </Text>
        </Stat>
        <Stat label="Added">{dateLabel(row.listing.created_at)}</Stat>
      </Box>

      <Box className={`${classes.stats} ${classes.statsTwo}`}>
        <Stat label="Status">
          {group ? (
            <CurationCell
              status={row.state?.interest_status ?? null}
              visited={visited}
              disabled={!canCurate || patchState.isPending}
              onStatus={(next) => save(next, visited)}
              onVisited={(next) => save(row.state?.interest_status ?? null, next)}
            />
          ) : (
            "—"
          )}
        </Stat>
        <Stat label="People">
          <RatingSummary
            ratings={rowRatings}
            members={members}
            commentCount={rowComments.length}
          />
        </Stat>
      </Box>

      <Box className={classes.actions}>
        <Button
          variant="default"
          size="xs"
          leftSection={<IconExternalLink size={14} stroke={1.5} />}
          disabled={!listingUrl}
          onClick={() => listingUrl && window.open(listingUrl, "_blank", "noopener")}
        >
          Listing
        </Button>
        <Button
          variant="default"
          size="xs"
          leftSection={<IconArrowsLeftRight size={14} stroke={1.5} />}
          disabled={entry === null || (compare.isFull && !compare.has(entry))}
          onClick={() => entry && compare.toggle(entry)}
        >
          {entry && compare.has(entry) ? "Remove" : "Compare"}
        </Button>
        {onArchive && (
          <Button
            variant="default"
            size="xs"
            color="red"
            leftSection={<IconArchive size={14} stroke={1.5} />}
            onClick={() => onArchive(row)}
          >
            Archive
          </Button>
        )}
      </Box>
    </Box>
  );
}

function OverviewRowCard({
  row,
  huntId,
  pipeline,
  onOpen,
  onArchive,
  staleClasses,
  autoResolved,
}: {
  row: OverviewRow;
  huntId: string;
  pipeline: RowPipeline | null;
  onOpen: (row: OverviewRow) => void;
  onArchive?: (row: OverviewRow) => void;
  staleClasses: RefreshClass[];
  autoResolved: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const group = row.group;
  const availability = rowAvailability(row);
  const blank = pipeline?.placeholder ?? false;

  // A row that is still working, or that failed, has nothing to expand — the
  // whole card is the hand-off to Tasks.
  if (blank && pipeline) {
    const working = pipeline.state === "working";
    return (
      <Box className={classes.row}>
        <Box
          component={Link}
          to={`/h/${huntId}/tasks${working ? "" : "?tab=history"}`}
          className={classes.main}
          style={{ textDecoration: "none", color: "inherit" }}
        >
          <RowMarker pipeline={pipeline.state} status={null} />
          <Box style={{ minWidth: 0 }}>
            <Text size="sm" fw={600} truncate>
              {row.listing.property.name}
            </Text>
            <Tooltip
              label={pipeline.detail}
              openDelay={300}
              multiline
              maw={320}
              disabled={
                !(pipeline.state === "failed" && pipeline.detail && pipelineErrorWasTruncated(pipeline.detail))
              }
            >
              <Text size="xs" c={working ? "dusky" : "red"} truncate>
                {working
                  ? `Working${pipeline.detail ? ` · ${sentenceCase(pipeline.detail.toLowerCase())}` : ""}`
                  : pipelineFailureLabel(pipeline.detail)}
              </Text>
            </Tooltip>
          </Box>
          <Anchor component="span" size="xs" fw={600} style={{ whiteSpace: "nowrap" }}>
            {working ? "View task" : "See history"} ›
          </Anchor>
        </Box>
      </Box>
    );
  }

  return (
    <Box className={classes.row} style={{ opacity: availability === "unavailable" ? 0.65 : 1 }}>
      <Box className={classes.main}>
        <UnstyledButton
          onClick={() => onOpen(row)}
          style={{ display: "contents" }}
          aria-label={`open ${row.listing.property.name}`}
        >
          <Box>
            {group?.displayScore ? (
              <ScoreCell
                total={group.displayScore.total}
                pinned={group.pinnedPlanId !== null}
                filterSelected={group.filterSelectedPlanId !== null}
                planName={group.displayPlan.plan_name}
                planCount={group.scoredPlanCount}
              />
            ) : (
              <Text size="xs" c="dimmed">
                {availability === "unavailable" ? "None" : "Pending"}
              </Text>
            )}
          </Box>
          <Box style={{ minWidth: 0 }}>
            <Box className={classes.name}>
              <RowMarker pipeline={pipeline?.state ?? null} status={row.state?.interest_status ?? null} />
              <Text size="sm" fw={600} truncate>
                {row.listing.property.name}
              </Text>
              {autoResolved && <AutoResolvedBadge />}
              <StaleBadge classes={staleClasses} />
            </Box>
            <Group gap={6} wrap="nowrap" mt={2}>
              <Text size="xs" c="dimmed">
                {group === null
                  ? "—"
                  : `${group.beds === 0 ? "Studio" : `${group.beds} bd`} / ${group.baths} ba`}
              </Text>
              <Text size="xs" c="dimmed">
                ·
              </Text>
              <AllInCell allIn={allInValue(row)} composition={rowComposition(row)} />
            </Group>
          </Box>
        </UnstyledButton>
        <ActionIcon
          variant="subtle"
          color="gray"
          c="dimmed"
          aria-label={expanded ? "hide detail" : "show detail"}
          aria-expanded={expanded}
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded ? <IconChevronUp size={16} stroke={1.5} /> : <IconChevronDown size={16} stroke={1.5} />}
        </ActionIcon>
      </Box>
      <Collapse expanded={expanded}>
        <ExpandedDetail row={row} huntId={huntId} onArchive={onArchive} />
      </Collapse>
    </Box>
  );
}

export function OverviewRowList({
  huntId,
  rows,
  pipeline,
  staleClassesByListing,
  autoResolvedListingIds,
  onOpen,
  onArchive,
}: {
  huntId: string;
  rows: OverviewRow[];
  pipeline?: Map<string, RowPipeline>;
  staleClassesByListing?: Map<string, RefreshClass[]>;
  autoResolvedListingIds?: Set<string>;
  onOpen: (row: OverviewRow) => void;
  onArchive?: (row: OverviewRow) => void;
}) {
  return (
    <Stack gap="xs">
      {rows.map((row) => (
        <OverviewRowCard
          key={rowKey(row)}
          row={row}
          huntId={huntId}
          pipeline={pipeline?.get(rowKey(row)) ?? null}
          staleClasses={staleClassesByListing?.get(row.listing.id) ?? []}
          autoResolved={autoResolvedListingIds?.has(row.listing.id) ?? false}
          onOpen={onOpen}
          onArchive={onArchive}
        />
      ))}
    </Stack>
  );
}
