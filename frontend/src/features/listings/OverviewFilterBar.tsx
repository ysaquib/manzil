// Extensible overview filter bar (§13.2). Active filters show as removable
// Pills; the panel expands for all filter inputs.
// To add a filter: extend OverviewFilterState + FILTER_PREDICATES in
// overviewRows.ts, add an input here, and add a label in filterPills().
import {
  Badge,
  Button,
  Collapse,
  Group,
  MultiSelect,
  NumberInput,
  Pill,
  Stack,
  Select,
  Text,
  Tooltip,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { useDisclosure } from "@mantine/hooks";
import { IconFilter, IconWorld } from "@tabler/icons-react";
import { sentenceCase } from "../../lib/text";
import { INTEREST_STATUSES } from "./types";

import {
  COOLING_VALUES,
  DEFAULT_OVERVIEW_FILTERS,
  filterPills,
  filtersEqual,
  hasActiveFilters,
  LAUNDRY_VALUES,
  PARKING_VALUES,
  PETS_VALUES,
  type FilterPillKey,
  type OverviewFilterState,
  type StatusFilter,
} from "./overviewRows";

const enumData = (values: readonly string[]) =>
  values.map((value) => ({ value, label: sentenceCase(value) }));

const dimmedLabel = { label: { fontWeight: 400, color: "var(--mantine-color-dimmed)" } };

export function OverviewFilterBar({
  filters,
  onChange,
  cities,
  visibleCount,
  totalCount,
  sharedFilters = null,
  canPublish = false,
  onPublish,
  publishPending = false,
}: {
  filters: OverviewFilterState;
  onChange: (next: OverviewFilterState) => void;
  cities: string[];
  visibleCount: number;
  totalCount: number;
  /** The published hunt-wide filter set (sanitized), or null when none. */
  sharedFilters?: OverviewFilterState | null;
  canPublish?: boolean;
  onPublish?: (filters: OverviewFilterState) => void;
  publishPending?: boolean;
}) {
  const [opened, { toggle }] = useDisclosure(false);
  const pills = filterPills(filters);
  const activeCount = pills.length;
  const filtersActive = hasActiveFilters(filters);
  const filteredOut = Math.max(0, totalCount - visibleCount);
  // A shared set equal to the defaults is "no shared filters" — publishing
  // cleared filters is how an Owner/Curator retires the hunt-wide set.
  const sharedActive = sharedFilters !== null && hasActiveFilters(sharedFilters);
  const matchesShared = sharedActive && filtersEqual(filters, sharedFilters);
  const canPublishNow =
    canPublish && onPublish !== undefined && !matchesShared &&
    (filtersActive || sharedActive);

  const setField = <K extends FilterPillKey>(key: K, value: OverviewFilterState[K]) =>
    onChange({ ...filters, [key]: value });

  const removePill = (key: FilterPillKey) =>
    setField(key, DEFAULT_OVERVIEW_FILTERS[key] as OverviewFilterState[typeof key]);

  return (
    <Stack gap="xs">
      <Group gap="sm" wrap="wrap" align="center">
        <Button
          variant="light"
          size="xs"
          leftSection={<IconFilter size={14} stroke={1.5} />}
          onClick={toggle}
          aria-expanded={opened}
        >
          Filters{activeCount > 0 ? ` (${activeCount})` : ""}
        </Button>
        {sharedActive && (
          <Tooltip
            label={
              matchesShared
                ? "These filters are the hunt-wide default every member starts from."
                : "You've changed filters locally — the hunt-wide default is unchanged."
            }
            openDelay={300}
          >
            <Badge
              variant={matchesShared ? "light" : "outline"}
              color={matchesShared ? undefined : "gray"}
              leftSection={<IconWorld size={12} stroke={1.5} />}
              style={{ textTransform: "none" }}
            >
              {matchesShared ? "Hunt-wide filters" : "Hunt-wide · modified"}
            </Badge>
          </Tooltip>
        )}
        {sharedActive && !matchesShared && (
          <Button variant="subtle" size="compact-xs" onClick={() => onChange(sharedFilters)}>
            Reset to hunt-wide
          </Button>
        )}
        {pills.map((pill) => (
          <Pill
            key={`${pill.key}:${pill.label}`}
            size="sm"
            withRemoveButton
            onRemove={() => removePill(pill.key)}
          >
            {pill.label}
          </Pill>
        ))}
        {filtersActive && (
          <Text size="xs" c="dimmed">
            {visibleCount} visible · {filteredOut} filtered out
          </Text>
        )}
      </Group>

      <Collapse expanded={opened}>
        <Stack gap="sm">
          <Group gap="md" wrap="wrap" align="flex-end">
            <NumberInput
              label="Hide score below"
              placeholder="off"
              value={filters.minScore ?? ""}
              onChange={(next) =>
                setField("minScore", typeof next === "number" ? next : null)
              }
              min={0}
              max={15}
              w={140}
              size="xs"
              styles={dimmedLabel}
            />
            <NumberInput
              label="Maximum score"
              placeholder="off"
              value={filters.maxScore ?? ""}
              onChange={(next) => setField("maxScore", typeof next === "number" ? next : null)}
              min={0}
              max={15}
              w={140}
              size="xs"
              styles={dimmedLabel}
            />
            <MultiSelect
              label="City"
              placeholder="any"
              data={cities}
              value={filters.cities}
              onChange={(value) => setField("cities", value)}
              searchable
              clearable
              w={180}
              size="xs"
              styles={dimmedLabel}
            />
            <MultiSelect
              label="Interest status"
              placeholder="any"
              data={["undecided", ...INTEREST_STATUSES].map((status) => ({
                value: status,
                label: sentenceCase(status),
              }))}
              value={filters.statuses}
              onChange={(value) => setField("statuses", value as StatusFilter[])}
              clearable
              w={200}
              size="xs"
              styles={dimmedLabel}
            />
            <Select
              label="Visited"
              placeholder="any"
              data={[{ value: "yes", label: "Visited" }, { value: "no", label: "Not visited" }]}
              value={filters.visited === null ? null : filters.visited ? "yes" : "no"}
              onChange={(value) => setField("visited", value === null ? null : value === "yes")}
              clearable
              w={140}
              size="xs"
              styles={dimmedLabel}
            />
            <MultiSelect
              label="Availability"
              placeholder="any"
              data={["scored", "pending", "unavailable"].map((availability) => ({
                value: availability,
                label: sentenceCase(availability),
              }))}
              value={filters.availabilities}
              onChange={(value) => setField("availabilities", value as OverviewFilterState["availabilities"])}
              clearable
              w={170}
              size="xs"
              styles={dimmedLabel}
            />
            <NumberInput
              label="Min rent"
              placeholder="any"
              value={filters.minRent ?? ""}
              onChange={(next) =>
                setField("minRent", typeof next === "number" ? next : null)
              }
              min={0}
              prefix="$"
              thousandSeparator
              w={120}
              size="xs"
              styles={dimmedLabel}
            />
            <NumberInput
              label="Max rent"
              placeholder="any"
              value={filters.maxRent ?? ""}
              onChange={(next) =>
                setField("maxRent", typeof next === "number" ? next : null)
              }
              min={0}
              prefix="$"
              thousandSeparator
              w={120}
              size="xs"
              styles={dimmedLabel}
            />
            <NumberInput
              label="Min sqft"
              placeholder="any"
              value={filters.minSqft ?? ""}
              onChange={(next) =>
                setField("minSqft", typeof next === "number" ? next : null)
              }
              min={0}
              thousandSeparator
              w={110}
              size="xs"
              styles={dimmedLabel}
            />
            <NumberInput
              label="Max sqft"
              placeholder="any"
              value={filters.maxSqft ?? ""}
              onChange={(next) =>
                setField("maxSqft", typeof next === "number" ? next : null)
              }
              min={0}
              thousandSeparator
              w={110}
              size="xs"
              styles={dimmedLabel}
            />
            <NumberInput
              label="Min beds"
              placeholder="any"
              value={filters.minBeds ?? ""}
              onChange={(next) =>
                setField("minBeds", typeof next === "number" ? next : null)
              }
              min={0}
              max={5}
              allowDecimal={false}
              w={100}
              size="xs"
              styles={dimmedLabel}
            />
            <NumberInput
              label="Max beds"
              placeholder="any"
              value={filters.maxBeds ?? ""}
              onChange={(next) =>
                setField("maxBeds", typeof next === "number" ? next : null)
              }
              min={0}
              max={5}
              allowDecimal={false}
              w={100}
              size="xs"
              styles={dimmedLabel}
            />
            <NumberInput
              label="Min baths"
              placeholder="any"
              value={filters.minBaths ?? ""}
              onChange={(next) =>
                setField("minBaths", typeof next === "number" ? next : null)
              }
              min={0}
              max={4}
              step={0.5}
              decimalScale={1}
              w={100}
              size="xs"
              styles={dimmedLabel}
            />
            <NumberInput
              label="Max baths"
              placeholder="any"
              value={filters.maxBaths ?? ""}
              onChange={(next) =>
                setField("maxBaths", typeof next === "number" ? next : null)
              }
              min={0}
              max={4}
              step={0.5}
              decimalScale={1}
              w={100}
              size="xs"
              styles={dimmedLabel}
            />
            <NumberInput
              label="Max all-in cost"
              placeholder="any"
              value={filters.maxAllIn ?? ""}
              onChange={(next) =>
                setField("maxAllIn", typeof next === "number" ? next : null)
              }
              min={0}
              prefix="$"
              thousandSeparator
              w={140}
              size="xs"
              styles={dimmedLabel}
            />
            <DatePickerInput
              label="Available by"
              placeholder="any date"
              value={filters.availableBy}
              onChange={(value) => setField("availableBy", value)}
              clearable
              valueFormat="MMM D, YYYY"
              w={160}
              size="xs"
              styles={dimmedLabel}
            />
            <MultiSelect
              label="Laundry"
              placeholder="any"
              data={enumData(LAUNDRY_VALUES)}
              value={filters.laundry}
              onChange={(value) => setField("laundry", value)}
              clearable
              w={170}
              size="xs"
              styles={dimmedLabel}
            />
            <MultiSelect
              label="Parking"
              placeholder="any"
              data={enumData(PARKING_VALUES)}
              value={filters.parking}
              onChange={(value) => setField("parking", value)}
              clearable
              w={180}
              size="xs"
              styles={dimmedLabel}
            />
            <MultiSelect
              label="Pets"
              placeholder="any"
              data={enumData(PETS_VALUES)}
              value={filters.pets}
              onChange={(value) => setField("pets", value)}
              clearable
              w={180}
              size="xs"
              styles={dimmedLabel}
            />
            <MultiSelect
              label="Cooling"
              placeholder="any"
              data={enumData(COOLING_VALUES)}
              value={filters.cooling}
              onChange={(value) => setField("cooling", value)}
              clearable
              w={160}
              size="xs"
              styles={dimmedLabel}
            />
            <Select
              label="Dishwasher"
              placeholder="any"
              data={[
                { value: "yes", label: "Has dishwasher" },
                { value: "no", label: "No dishwasher" },
              ]}
              value={filters.dishwasher === null ? null : filters.dishwasher ? "yes" : "no"}
              onChange={(value) =>
                setField("dishwasher", value === null ? null : value === "yes")
              }
              clearable
              w={150}
              size="xs"
              styles={dimmedLabel}
            />
          </Group>
          <Group gap="sm">
            {hasActiveFilters(filters) && (
              <Button
                variant="subtle"
                size="xs"
                onClick={() => onChange(DEFAULT_OVERVIEW_FILTERS)}
              >
                Clear all
              </Button>
            )}
            {canPublishNow && (
              <Tooltip
                label="Publish these filters as the view every member starts from when they open this hunt."
                openDelay={300}
              >
                <Button
                  variant="light"
                  size="xs"
                  leftSection={<IconWorld size={14} stroke={1.5} />}
                  loading={publishPending}
                  onClick={() => onPublish?.(filters)}
                >
                  Apply hunt-wide
                </Button>
              </Tooltip>
            )}
          </Group>
        </Stack>
      </Collapse>
    </Stack>
  );
}
