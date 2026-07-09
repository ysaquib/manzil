// Overview table (P1-10, §13.2): plain Mantine Table over the tested pure row
// logic (mantine-react-table is incompatible with Mantine v9, and the column
// set is small). One row per Unit Group; score cell shows the group's best or
// pinned plan (§9.4). Sqft/all-in columns hide below md/sm — no horizontal
// page scroll (frontend/AGENTS.md).
import { ActionIcon, Group, Menu, Table, Text, UnstyledButton } from "@mantine/core";
import { IconChevronDown, IconChevronUp, IconDotsVertical, IconTrash } from "@tabler/icons-react";

import { ScoreCell } from "./ScoreCell";
import { formatRange, type OverviewRow, type SortKey, type SortState } from "./overviewRows";

// Effective all-in monthly cost: read from the persisted breakdown (never
// recomputed client-side). Phase 1 carries the interim composition (advertised
// rent); the estimated-portion split renders once P3-9's real composition
// lands — no fabricated "~est" until then.
export function allInValue(row: OverviewRow): number | null {
  const criteria = row.group.displayScore?.breakdown.criteria ?? [];
  const value = criteria.find((c) => c.key === "all_in_monthly")?.value;
  return typeof value === "number" ? value : null;
}

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
  const SortIcon = active ? (sort.dir === "asc" ? IconChevronUp : IconChevronDown) : null;
  return (
    <UnstyledButton onClick={() => onSort(sortKey)} aria-label={`sort by ${label}`}>
      <Group gap={4} wrap="nowrap">
        <Text size="sm" fw={active ? 700 : 500} span>
          {label}
        </Text>
        {SortIcon && <SortIcon size={14} stroke={1.5} />}
      </Group>
    </UnstyledButton>
  );
}

export interface OverviewTableProps {
  rows: OverviewRow[];
  sort: SortState;
  onSort: (key: SortKey) => void;
  onOpen: (row: OverviewRow) => void;
  onDelete: (row: OverviewRow) => void;
}

export function OverviewTable({ rows, sort, onSort, onOpen, onDelete }: OverviewTableProps) {
  return (
    <Table striped highlightOnHover verticalSpacing="sm">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>
            <SortHeader label="Property" sortKey="name" sort={sort} onSort={onSort} />
          </Table.Th>
          <Table.Th>Unit</Table.Th>
          <Table.Th>
            <SortHeader label="Score" sortKey="score" sort={sort} onSort={onSort} />
          </Table.Th>
          <Table.Th>
            <SortHeader label="Rent" sortKey="rent" sort={sort} onSort={onSort} />
          </Table.Th>
          <Table.Th visibleFrom="md">Sqft</Table.Th>
          <Table.Th visibleFrom="sm">All-in / mo</Table.Th>
          <Table.Th aria-label="row actions" />
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((row) => {
          const allIn = allInValue(row);
          return (
            <Table.Tr
              key={`${row.listing.id}:${row.group.key}`}
              onClick={() => onOpen(row)}
              style={{ cursor: "pointer" }}
            >
              <Table.Td>
                <Text size="sm" fw={600}>
                  {row.listing.property.name}
                </Text>
                <Text size="xs" c="dimmed">
                  {row.listing.property.canonical_address}
                </Text>
              </Table.Td>
              <Table.Td>
                <Text size="sm">
                  {row.group.beds === 0 ? "Studio" : `${row.group.beds} bd`} /{" "}
                  {row.group.baths} ba
                </Text>
              </Table.Td>
              <Table.Td>
                {row.group.displayScore ? (
                  <ScoreCell
                    total={row.group.displayScore.total}
                    scoredPlanCount={row.group.scoredPlanCount}
                    pinned={row.group.pinnedPlanId !== null}
                  />
                ) : (
                  <Text size="sm" c="dimmed">
                    pending
                  </Text>
                )}
              </Table.Td>
              <Table.Td>
                <Text size="sm">{formatRange(row.group.rentMin, row.group.rentMax, "$")}</Text>
              </Table.Td>
              <Table.Td visibleFrom="md">
                <Text size="sm">{formatRange(row.group.sqftMin, row.group.sqftMax)}</Text>
              </Table.Td>
              <Table.Td visibleFrom="sm">
                <Text size="sm">{allIn === null ? "—" : `$${allIn.toLocaleString()}`}</Text>
              </Table.Td>
              <Table.Td onClick={(e) => e.stopPropagation()} width={40}>
                <Menu position="bottom-end" withinPortal>
                  <Menu.Target>
                    <ActionIcon color="gray" aria-label="listing actions">
                      <IconDotsVertical size={16} stroke={1.5} />
                    </ActionIcon>
                  </Menu.Target>
                  <Menu.Dropdown>
                    <Menu.Item
                      color="red"
                      leftSection={<IconTrash size={14} stroke={1.5} />}
                      onClick={() => onDelete(row)}
                    >
                      Delete listing…
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
