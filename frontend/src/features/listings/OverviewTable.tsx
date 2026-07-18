// Overview table (P1-10, §13.2): plain Mantine Table over the tested pure row
// logic (mantine-react-table is incompatible with Mantine v9, and the column
// set is small). One row per Unit Group; score cell shows the group's best or
// pinned plan (§9.4). Sqft/all-in columns hide below md/sm — no horizontal
// page scroll (frontend/AGENTS.md).
import { ActionIcon, Checkbox, Group, Menu, Select, Table, Text, Tooltip, UnstyledButton } from "@mantine/core";
import { IconChevronDown, IconChevronRight, IconChevronUp, IconDotsVertical, IconMessageCircle, IconTrash } from "@tabler/icons-react";

import { AllInCell } from "./AllInCost";
import { ScoreCell } from "./ScoreCell";
import { RatingDots } from "../collaboration/RatingDots";
import { useComments, useCurrentMember, useMembers, useRatings } from "../collaboration/api";
import { usePatchUnitGroupState } from "./api";
import { INTEREST_STATUSES, type InterestStatus } from "./types";
import {
  allInValue,
  formatRange,
  rowAvailability,
  rowComposition,
  type OverviewRow,
  type SortKey,
  type SortState,
} from "./overviewRows";
import { sentenceCase } from "../../lib/text";

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
        <Text size="sm" span fw={700}>
          {label}
        </Text>
        <SortIcon size={14} stroke={1.5} />
      </Group>
    </UnstyledButton>
  );
}

export interface OverviewTableProps {
  huntId: string;
  rows: OverviewRow[];
  sort: SortState;
  onSort: (key: SortKey) => void;
  onOpen: (row: OverviewRow) => void;
  onDelete: (row: OverviewRow) => void;
}

function CollaborationCell({ listingId, huntId, unitGroupKey }: { listingId: string; huntId: string; unitGroupKey: string | null }) {
  const { data: members = [] } = useMembers(huntId);
  const { data: ratings = [] } = useRatings(listingId);
  const { data: comments = [] } = useComments(listingId);
  const rowRatings = ratings.filter((rating) => rating.unit_group_key === unitGroupKey);
  const rowComments = comments.filter(
    (comment) => comment.unit_group_key === null || comment.unit_group_key === unitGroupKey,
  );
  return (
    <Group gap="sm" wrap="nowrap">
      <RatingDots ratings={rowRatings} members={members} />
      {rowComments.length > 0 && (
        <Group gap={4} wrap="nowrap">
          <Text size="sm" c="default">{rowComments.length}</Text>
          <IconMessageCircle size={16} stroke={1.5}/>
        </Group>
      )}
      {/* {comments.length > 0 && <Text size="xs" c="dimmed">{comments.length} comments</Text>} */}
    </Group>
  );
}

function CurationCells({ row, huntId }: { row: OverviewRow; huntId: string }) {
  const { data: currentMember } = useCurrentMember(huntId);
  const patchState = usePatchUnitGroupState(huntId);
  const canCurate = currentMember?.role === "owner" || currentMember?.role === "curator";
  const group = row.group;
  const save = (interest_status: InterestStatus | null, visited: boolean) => {
    if (!group) return;
    patchState.mutate({
      listingId: row.listing.id,
      unitGroupKey: group.key,
      interest_status,
      visited,
    });
  };
  const visited = row.state?.visited ?? false;
  // One curation cell (§13.2 declutter): status select + visited toggle share
  // a column instead of owning one each.
  return (
    <Table.Td onClick={(event) => event.stopPropagation()}>
      {group ? (
        <Group gap="xs" wrap="nowrap">
          <Select
            aria-label="interest status"
            placeholder="Undecided"
            data={INTEREST_STATUSES.map((status) => ({
              value: status,
              label: sentenceCase(status),
            }))}
            value={row.state?.interest_status ?? null}
            onChange={(value) => save(value as InterestStatus | null, visited)}
            disabled={!canCurate || patchState.isPending}
            clearable
            size="xs"
            w={140}
          />
          <Tooltip label={visited ? "Visited" : "Mark visited"} openDelay={300}>
            <Checkbox
              aria-label="visited"
              checked={visited}
              disabled={!canCurate || patchState.isPending}
              onChange={(event) =>
                save(row.state?.interest_status ?? null, event.currentTarget.checked)
              }
            />
          </Tooltip>
        </Group>
      ) : <Text size="sm" c="dimmed">—</Text>}
    </Table.Td>
  );
}

export function OverviewTable({ huntId, rows, sort, onSort, onOpen, onDelete }: OverviewTableProps) {
  return (
    <Table striped highlightOnHover verticalSpacing="sm">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>
            <SortHeader label="Score" sortKey="score" sort={sort} onSort={onSort} />
          </Table.Th>
          <Table.Th>
            <SortHeader label="Property" sortKey="name" sort={sort} onSort={onSort} />
          </Table.Th>
          <Table.Th>Unit</Table.Th>
          <Table.Th>
            <SortHeader label="Rent" sortKey="rent" sort={sort} onSort={onSort} />
          </Table.Th>
          <Table.Th visibleFrom="md">Sqft</Table.Th>
          <Table.Th visibleFrom="sm">All-in / mo</Table.Th>
          <Table.Th>Status</Table.Th>
          <Table.Th>People</Table.Th>
          <Table.Th aria-label="row actions" />
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((row) => {
          const allIn = allInValue(row);
          const group = row.group;
          const availability = rowAvailability(row);
          return (
            <Table.Tr
              key={`${row.listing.id}:${group?.key ?? "listing"}`}
              onClick={() => onOpen(row)}
              // A no-availability listing is dimmed — present but nothing to rank on.
              style={{ cursor: "pointer", opacity: availability === "unavailable" ? 0.55 : 1 }}
            >
              <Table.Td>
                {group?.displayScore ? (
                  <ScoreCell
                    total={group.displayScore.total}
                    pinned={group.pinnedPlanId !== null}
                    planCount={group.scoredPlanCount}
                  />
                ) : (
                  <Text size="sm" c="dimmed">
                    {availability === "unavailable" ? "No availability" : "Pending"}
                  </Text>
                )}
              </Table.Td>
              <Table.Td>
                <Text size="sm" fw={600}>
                  {row.listing.property.name}
                </Text>
                <Text size="xs" c="dimmed">
                  {row.listing.property.canonical_address}
                </Text>
              </Table.Td>
              <Table.Td>
                <Text size="sm" lh={1}>
                  {group === null
                    ? "—"
                    : `${group.beds === 0 ? "Studio" : `${group.beds} bd`} / ${group.baths} ba`}
                </Text>
              </Table.Td>
              <Table.Td>
                <Text size="sm">
                  {group === null ? "—" : formatRange(group.rentMin, group.rentMax, "$")}
                </Text>
              </Table.Td>
              <Table.Td visibleFrom="md">
                <Text size="sm">
                  {group === null ? "—" : formatRange(group.sqftMin, group.sqftMax)}
                </Text>
              </Table.Td>
              <Table.Td visibleFrom="sm">
                <AllInCell allIn={allIn} composition={rowComposition(row)} />
              </Table.Td>
              <CurationCells row={row} huntId={huntId} />
              <Table.Td>
                <CollaborationCell
                  listingId={row.listing.id}
                  huntId={huntId}
                  unitGroupKey={group?.key ?? null}
                />
              </Table.Td>
              <Table.Td onClick={(e) => e.stopPropagation()} width={40}>
                <Menu position="bottom-end" withinPortal>
                  <Menu.Target>
                    <ActionIcon color="gray" c="dimmed" aria-label="listing actions">
                      <IconDotsVertical size={16} stroke={1.5} />
                    </ActionIcon>
                  </Menu.Target>
                  <Menu.Dropdown>
                    <Menu.Item
                      color="red"
                      leftSection={<IconTrash size={14} stroke={1.5} />}
                      onClick={() => onDelete(row)}
                    >
                      Delete listing
                    </Menu.Item>
                  </Menu.Dropdown>
                </Menu>
              </Table.Td>
            </Table.Tr>
          );
        })}
      </Table.Tbody>
    </Table>
  );
}
