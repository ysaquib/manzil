// Compare view (P3-13 compare half, §13.2/§13.1 route): side-by-side detail
// for the Unit Group rows sent here from the Overview. Transposed table —
// attributes as rows, one column per compared group (≤ COMPARE_LIMIT). The
// criteria section iterates the union of score-breakdown entries, so custom
// criteria (P3-10) will appear with zero changes here.
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { useLocalStorage } from "@mantine/hooks";
import { DragDropProvider } from "@dnd-kit/react";
import { useSortable } from "@dnd-kit/react/sortable";
import {
  IconArrowsLeftRight,
  IconExternalLink,
  IconGripVertical,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { sentenceCase } from "../../lib/text";
import { labelByKeyFromCatalog } from "../rubric/customCriterion";
import { useResolvedCatalog } from "../rubric/api";
import { useExtractions, useListings, usePropertyImages, useUnitGroupStates } from "./api";
import { AllInCell } from "./AllInCost";
import { COMPARE_LIMIT, entryKey, useCompareSet, type CompareEntry } from "./compareSet";
import { displayValue } from "./displayValue";
import { extractionForFloorPlan } from "./overrides";
import {
  buildRows,
  earliestAvailability,
  formatRange,
  rowAvailability,
  rowComposition,
  type OverviewRow,
} from "./overviewRows";
import { TableDensityMenu, type TableDensity } from "./OverviewTable";
import { PropertyImageCarousel } from "./PropertyImageCarousel";
import { ScoreCell } from "./ScoreCell";
import { useHuntAccess } from "../hunts/access";

import classes from "./ComparePage.module.css";

const DENSITY_VERTICAL: Record<TableDensity, string | number> = {
  compact: 4,
  normal: "sm",
  comfortable: "lg",
};

function deltaBadge(delta: number) {
  const color = delta > 0 ? "green" : delta < 0 ? "red" : "gray";
  return (
    <Badge color={color} variant="light" size="sm">
      {delta > 0 ? "+" : ""}
      {delta}
    </Badge>
  );
}

function PhotosCell({ propertyId }: { propertyId: string }) {
  const { data: images = [], isLoading } = usePropertyImages(propertyId);
  return <PropertyImageCarousel images={images} loading={isLoading} />;
}

function CriterionCell({
  column,
  criterionKey,
  huntId,
}: {
  column: CompareColumn;
  criterionKey: string;
  huntId: string;
}) {
  const criterion = column.row.group?.displayScore?.breakdown.criteria.find(
    (candidate) => candidate.key === criterionKey,
  );
  const { data: extractions = [] } = useExtractions(column.row.listing.property_id, huntId);
  const extraction = extractionForFloorPlan(
    extractions,
    criterionKey,
    column.row.group?.displayPlan.id ?? null,
  );
  if (!criterion) {
    return <Text size="sm" c="dimmed">—</Text>;
  }
  return (
    <Stack gap={2}>
      <Group gap="xs" wrap="nowrap" justify="space-between">
        <Text size="sm">{displayValue(criterion.value, criterionKey)}</Text>
        {deltaBadge(criterion.delta)}
      </Group>
      {extraction?.resolution_rule === "vision_weighted_median_gallery" && (
        <Tooltip label="This kitchen may not represent this Floor Plan.">
          <Text size="xs" c="dimmed">Property-gallery estimate</Text>
        </Tooltip>
      )}
    </Stack>
  );
}

/** One compared column: a resolved Overview row (its entry still valid). */
interface CompareColumn {
  entry: CompareEntry;
  row: OverviewRow;
}

function LabelCell({ children }: { children: React.ReactNode }) {
  return (
    <Table.Th scope="row" className={classes.labelCol}>
      <Text size="sm" fw={600} c="dimmed">
        {children}
      </Text>
    </Table.Th>
  );
}

function SectionRow({ label, span }: { label: string; span: number }) {
  return (
    <Table.Tr className={classes.sectionRow}>
      <Table.Th scope="row" className={classes.labelCol}>
        <Text size="xs" fw={700} tt="uppercase" c="dimmed" lts="0.06em">
          {label}
        </Text>
      </Table.Th>
      <Table.Td colSpan={span} />
    </Table.Tr>
  );
}

function SortableCompareHeader({
  column,
  index,
  count,
  readOnly,
  onRemove,
}: {
  column: CompareColumn;
  index: number;
  count: number;
  readOnly: boolean;
  onRemove: () => void;
}) {
  const key = entryKey(column.entry);
  const { ref, handleRef, isDragging } = useSortable({
    id: key,
    index,
    group: "compare-columns",
    disabled: readOnly || count < 2,
  });
  const property = column.row.listing.property;
  const listingUrl = property.official_url ?? property.sources[0]?.url ?? null;

  return (
    <Table.Th
      ref={ref}
      className={classes.valueCol}
      style={{ opacity: isDragging ? 0.55 : 1 }}
    >
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Group gap={6} wrap="nowrap" align="flex-start">
          {count > 1 && !readOnly && (
            <ActionIcon
              ref={handleRef}
              variant="subtle"
              color="gray"
              size="sm"
              aria-label={`Reorder ${property.name}`}
              style={{ cursor: "grab", flexShrink: 0 }}
            >
              <IconGripVertical size={14} stroke={1.5} />
            </ActionIcon>
          )}
          <div>
            <Text size="md" fw={600} ff="heading">
              {property.name}
            </Text>
            <Text size="xs" c="dimmed" fw={400}>
              {property.canonical_address}
            </Text>
          </div>
        </Group>
        <Group gap={4} wrap="nowrap">
          {listingUrl && (
            <Tooltip label="Open listing page" openDelay={300}>
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label="open listing page"
                onClick={() => window.open(listingUrl, "_blank", "noopener")}
              >
                <IconExternalLink size={14} stroke={1.5} />
              </ActionIcon>
            </Tooltip>
          )}
          {!readOnly && (
            <Tooltip label="Remove from compare" openDelay={300}>
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label="remove from compare"
                onClick={onRemove}
              >
                <IconX size={14} stroke={1.5} />
              </ActionIcon>
            </Tooltip>
          )}
        </Group>
      </Group>
    </Table.Th>
  );
}

export function ComparePage() {
  const { huntId = "" } = useParams();
  const compare = useCompareSet(huntId);
  const { data: listings, isLoading, error } = useListings(huntId);
  const { data: unitGroupStates = [] } = useUnitGroupStates(huntId);
  const { data: catalog = [] } = useResolvedCatalog(huntId);
  const access = useHuntAccess(huntId);
  const [density, setDensity] = useLocalStorage<TableDensity>({
    key: "manzil:compare-density",
    defaultValue: "normal",
  });

  const rows = buildRows(listings ?? [], unitGroupStates);
  const rowByKey = new Map(
    rows
      .filter((row) => row.group !== null)
      .map((row) => [`${row.listing.id}:${row.group!.key}`, row]),
  );
  const columns: CompareColumn[] = compare.entries.flatMap((entry) => {
    const row = rowByKey.get(entryKey(entry));
    return row ? [{ entry, row }] : [];
  });

  // Prune entries whose listing/group vanished — but only from loaded data,
  // never while the query is still empty.
  useEffect(() => {
    if (!listings || !access.canMutate) return;
    compare.prune(new Set(rowByKey.keys()));
    // Deliberately narrow deps: rowByKey derives from exactly these inputs,
    // and compare.prune already no-ops when nothing changed.
  }, [listings, unitGroupStates, access.canMutate]);

  const labelByKey = labelByKeyFromCatalog(catalog);

  // Union of breakdown criteria across columns, first column's order first.
  const criterionKeys: string[] = [];
  for (const column of columns) {
    for (const criterion of column.row.group?.displayScore?.breakdown.criteria ?? []) {
      if (!criterionKeys.includes(criterion.key)) criterionKeys.push(criterion.key);
    }
  }

  // Union of monthly-composition component names, same ordering rule.
  const componentNames: string[] = [];
  for (const column of columns) {
    for (const component of rowComposition(column.row)?.components ?? []) {
      if (!componentNames.includes(component.name)) componentNames.push(component.name);
    }
  }

  const span = columns.length;
  const entryIndex = (key: string) =>
    compare.entries.findIndex((entry) => entryKey(entry) === key);

  return (
    <Stack gap="lg">
      <PageHeader
        title="Compare"
        description={`Side-by-side detail for up to ${COMPARE_LIMIT} unit groups sent from the Overview`}
      />

      <Group justify="space-between" wrap="wrap" gap="sm">
        <Text size="sm" c="dimmed">
          {columns.length === 0
            ? "Nothing to compare yet."
            : `Comparing ${columns.length} unit group${columns.length === 1 ? "" : "s"}.`}
        </Text>
        <Group gap="sm">
          {compare.entries.length > 0 && (
            <Button
              variant="subtle"
              size="xs"
              leftSection={<IconTrash size={14} stroke={1.5} />}
              onClick={compare.clear}
              disabled={!access.canMutate}
            >
              Clear compare
            </Button>
          )}
          <TableDensityMenu density={density} onChange={setDensity} />
        </Group>
      </Group>

      {isLoading && (
        <Center py="xl">
          <Loader />
        </Center>
      )}
      {error && (
        <Alert color="red" title="Couldn't load listings">
          {error.message} — try reloading the page.
        </Alert>
      )}
      {!isLoading && !error && columns.length === 0 && (
        <Card py="xl">
          <Stack align="center" gap="sm">
            <IconArrowsLeftRight size={32} stroke={1.5} color="var(--mantine-color-dimmed)" />
            <Text ta="center" c="dimmed">
              {access.canMutate
                ? "Send unit groups here with “Send to Compare” in an Overview row's ⋯ menu — up to 3 at a time."
                : "This read-only Hunt has no saved comparison set in this browser."}
            </Text>
            <Button component={Link} to={`/h/${huntId}`} variant="light" size="xs">
              Back to Overview
            </Button>
          </Stack>
        </Card>
      )}

      {columns.length > 0 && (
        <DragDropProvider
          onDragEnd={(event) => {
            if (event.canceled || !access.canMutate) return;
            const source = event.operation.source?.id;
            const target = event.operation.target?.id;
            if (source != null && target != null && source !== target) {
              compare.move(entryIndex(String(source)), entryIndex(String(target)));
            }
          }}
        >
        <div className={classes.scroller}>
          <Table
            verticalSpacing={DENSITY_VERTICAL[density]}
            horizontalSpacing="md"
            withColumnBorders
            className={classes.table}
          >
            <Table.Thead>
              <Table.Tr>
                <Table.Th className={classes.labelCol} aria-label="attribute" />
                {columns.map((column, index) => (
                  <SortableCompareHeader
                    key={entryKey(column.entry)}
                    column={column}
                    index={index}
                    count={columns.length}
                    readOnly={!access.canMutate}
                    onRemove={() => compare.remove(column.entry)}
                  />
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              <Table.Tr>
                <LabelCell>Photos</LabelCell>
                {columns.map((column) => (
                  <Table.Td key={entryKey(column.entry)} className={classes.photoCell}>
                    <PhotosCell propertyId={column.row.listing.property_id} />
                  </Table.Td>
                ))}
              </Table.Tr>

              <Table.Tr>
                <LabelCell>Score</LabelCell>
                {columns.map((column) => {
                  const group = column.row.group!;
                  return (
                    <Table.Td key={entryKey(column.entry)}>
                      {group.displayScore ? (
                        <ScoreCell
                          total={group.displayScore.total}
                          pinned={group.pinnedPlanId !== null}
                          planCount={group.scoredPlanCount}
                        />
                      ) : (
                        <Text size="sm" c="dimmed">
                          {rowAvailability(column.row) === "unavailable" ? "No availability" : "Pending"}
                        </Text>
                      )}
                    </Table.Td>
                  );
                })}
              </Table.Tr>
              <Table.Tr>
                <LabelCell>Unit group</LabelCell>
                {columns.map((column) => {
                  const group = column.row.group!;
                  return (
                    <Table.Td key={entryKey(column.entry)}>
                      <Text size="sm">
                        {`${group.beds === 0 ? "Studio" : `${group.beds} bd`} / ${group.baths} ba`}
                        {group.plans.length > 1 ? ` · ${group.plans.length} plans` : ""}
                      </Text>
                      {group.unitTypes.length > 0 && (
                        <Text size="xs" c="dimmed">
                          {group.unitTypes.map((type) => sentenceCase(type)).join(", ")}
                        </Text>
                      )}
                    </Table.Td>
                  );
                })}
              </Table.Tr>
              <Table.Tr>
                <LabelCell>Rent</LabelCell>
                {columns.map((column) => (
                  <Table.Td key={entryKey(column.entry)}>
                    <Text size="sm">
                      {formatRange(column.row.group!.rentMin, column.row.group!.rentMax, "$")}
                    </Text>
                  </Table.Td>
                ))}
              </Table.Tr>
              <Table.Tr>
                <LabelCell>Sqft</LabelCell>
                {columns.map((column) => (
                  <Table.Td key={entryKey(column.entry)}>
                    <Text size="sm">
                      {formatRange(column.row.group!.sqftMin, column.row.group!.sqftMax)}
                    </Text>
                  </Table.Td>
                ))}
              </Table.Tr>
              <Table.Tr>
                <LabelCell>All-in / mo</LabelCell>
                {columns.map((column) => (
                  <Table.Td key={entryKey(column.entry)}>
                    <AllInCell
                      allIn={rowComposition(column.row)?.total ?? null}
                      composition={rowComposition(column.row)}
                    />
                  </Table.Td>
                ))}
              </Table.Tr>
              <Table.Tr>
                <LabelCell>Deposit</LabelCell>
                {columns.map((column) => {
                  const deposit = column.row.group!.displayPlan.deposit;
                  return (
                    <Table.Td key={entryKey(column.entry)}>
                      <Text size="sm">{deposit === null ? "—" : `$${deposit.toLocaleString()}`}</Text>
                    </Table.Td>
                  );
                })}
              </Table.Tr>
              <Table.Tr>
                <LabelCell>Available</LabelCell>
                {columns.map((column) => {
                  const date = earliestAvailability(column.row);
                  return (
                    <Table.Td key={entryKey(column.entry)}>
                      <Text size="sm">
                        {date ? new Date(`${date}T00:00:00`).toLocaleDateString() : "—"}
                      </Text>
                    </Table.Td>
                  );
                })}
              </Table.Tr>
              <Table.Tr>
                <LabelCell>Interest</LabelCell>
                {columns.map((column) => {
                  const status = column.row.state?.interest_status;
                  const visited = column.row.state?.visited ?? false;
                  return (
                    <Table.Td key={entryKey(column.entry)}>
                      <Group gap="xs" wrap="nowrap">
                        <Text size="sm">{status ? sentenceCase(status) : "Undecided"}</Text>
                        {visited && (
                          <Badge variant="light" size="sm">
                            Visited
                          </Badge>
                        )}
                      </Group>
                    </Table.Td>
                  );
                })}
              </Table.Tr>

              {componentNames.length > 0 && <SectionRow label="Monthly costs" span={span} />}
              {componentNames.map((name) => (
                <Table.Tr key={`component:${name}`}>
                  <LabelCell>{sentenceCase(name)}</LabelCell>
                  {columns.map((column) => {
                    const component = rowComposition(column.row)?.components.find(
                      (c) => c.name === name,
                    );
                    if (!component) {
                      return (
                        <Table.Td key={entryKey(column.entry)}>
                          <Text size="sm" c="dimmed">
                            —
                          </Text>
                        </Table.Td>
                      );
                    }
                    return (
                      <Table.Td key={entryKey(column.entry)}>
                        <Text size="sm">
                          {component.amount === null
                            ? "unknown"
                            : `$${component.amount.toLocaleString()}`}
                          {component.tag === "estimated" && (
                            <Text span size="xs" c="dimmed">
                              {" "}
                              (est.)
                            </Text>
                          )}
                        </Text>
                      </Table.Td>
                    );
                  })}
                </Table.Tr>
              ))}

              {criterionKeys.length > 0 && <SectionRow label="Criteria" span={span} />}
              {criterionKeys.map((key) => (
                <Table.Tr key={`criterion:${key}`}>
                  <LabelCell>{labelByKey.get(key) ?? sentenceCase(key)}</LabelCell>
                  {columns.map((column) => {
                    return (
                      <Table.Td key={entryKey(column.entry)}>
                        <CriterionCell column={column} criterionKey={key} huntId={huntId} />
                      </Table.Td>
                    );
                  })}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </div>
        </DragDropProvider>
      )}
    </Stack>
  );
}
