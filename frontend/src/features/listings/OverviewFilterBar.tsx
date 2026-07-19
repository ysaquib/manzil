// Extensible overview filter bar (§13.2). Active filters show as removable
// Pills; the panel expands for all filter inputs.
// To add a filter: extend OverviewFilterState + FILTER_PREDICATES in
// overviewRows.ts, add an input here, and add a label in filterPills().
import {
  Button,
  Collapse,
  Group,
  MultiSelect,
  NumberInput,
  Pill,
  Stack,
  Select,
  Text,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconFilter } from "@tabler/icons-react";
import { sentenceCase } from "../../lib/text";
import { INTEREST_STATUSES } from "./types";

import {
  DEFAULT_OVERVIEW_FILTERS,
  filterPills,
  hasActiveFilters,
  type FilterPillKey,
  type OverviewFilterState,
  type StatusFilter,
} from "./overviewRows";

const dimmedLabel = { label: { fontWeight: 400, color: "var(--mantine-color-dimmed)" } };

export function OverviewFilterBar({
  filters,
  onChange,
  cities,
  visibleCount,
  totalCount,
}: {
  filters: OverviewFilterState;
  onChange: (next: OverviewFilterState) => void;
  cities: string[];
  visibleCount: number;
  totalCount: number;
}) {
  const [opened, { toggle }] = useDisclosure(false);
  const pills = filterPills(filters);
  const activeCount = pills.length;
  const filtersActive = hasActiveFilters(filters);
  const filteredOut = Math.max(0, totalCount - visibleCount);

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
          </Group>
          {hasActiveFilters(filters) && (
            <Button
              variant="subtle"
              size="xs"
              w="fit-content"
              onClick={() => onChange(DEFAULT_OVERVIEW_FILTERS)}
            >
              Clear all
            </Button>
          )}
        </Stack>
      </Collapse>
    </Stack>
  );
}
