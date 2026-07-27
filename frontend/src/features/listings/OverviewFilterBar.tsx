// Overview filter bar (§13.2; redesigned UI Decision Log 2026-07-26).
//
// Search and Filters share an edge so they read as one control rather than a
// pill floating with nothing to anchor it. The expanded panel groups 22 fields
// into labelled sections instead of one wrapping row of inputs: paired bounds
// share a row with a dash between them, and the small controlled vocabularies
// are Title Case toggle chips — every option visible, one click to set, and a
// single tap on a phone.
//
// To add a filter: extend OverviewFilterState + FILTER_PREDICATES in
// overviewRows.ts, add an input to the right section here, and add a label in
// filterPills().
import {
  Badge,
  Box,
  Button,
  Chip,
  Collapse,
  Group,
  NumberInput,
  Paper,
  Pill,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { useDisclosure } from "@mantine/hooks";
import { IconFilter, IconSearch, IconWorld } from "@tabler/icons-react";
import type { ReactNode } from "react";

import { titleCase } from "../../lib/text";
import { interestLabel } from "./interestStatus";
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

/** One labelled block in the panel grid. */
function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={6}>
      <Text size="xs" c="dimmed" fw={600} tt="uppercase" style={{ letterSpacing: "0.08em" }}>
        {label}
      </Text>
      {children}
    </Stack>
  );
}

/** A pair of bounds reading as one range, not two separately-labelled fields. */
function Range({
  min,
  max,
  onMin,
  onMax,
  prefix,
  step,
  minPlaceholder = "any",
  maxPlaceholder = "any",
  label,
}: {
  min: number | null;
  max: number | null;
  onMin: (next: number | null) => void;
  onMax: (next: number | null) => void;
  prefix?: string;
  step?: number;
  minPlaceholder?: string;
  maxPlaceholder?: string;
  label: string;
}) {
  const numeric = (next: string | number) => (typeof next === "number" ? next : null);
  return (
    <Group gap={6} wrap="nowrap">
      <NumberInput
        aria-label={`minimum ${label}`}
        placeholder={minPlaceholder}
        prefix={prefix}
        step={step}
        min={0}
        size="xs"
        value={min ?? ""}
        onChange={(next) => onMin(numeric(next))}
        style={{ flex: 1, minWidth: 0 }}
      />
      <Text size="xs" c="dimmed">
        —
      </Text>
      <NumberInput
        aria-label={`maximum ${label}`}
        placeholder={maxPlaceholder}
        prefix={prefix}
        step={step}
        min={0}
        size="xs"
        value={max ?? ""}
        onChange={(next) => onMax(numeric(next))}
        style={{ flex: 1, minWidth: 0 }}
      />
    </Group>
  );
}

/** A controlled vocabulary as toggle chips. */
function Toggles({
  values,
  selected,
  onChange,
  label,
  labelFor = titleCase,
}: {
  values: readonly string[];
  selected: string[];
  onChange: (next: string[]) => void;
  label: string;
  labelFor?: (value: string) => string;
}) {
  return (
    <Chip.Group multiple value={selected} onChange={onChange}>
      <Group gap={6} aria-label={label}>
        {values.map((value) => (
          <Chip key={value} value={value} size="xs" variant="outline">
            {labelFor(value)}
          </Chip>
        ))}
      </Group>
    </Chip.Group>
  );
}

/** A tri-state (any / yes / no) as a single-select chip row. */
function TriState({
  value,
  onChange,
  yes,
  no,
  label,
}: {
  value: boolean | null;
  onChange: (next: boolean | null) => void;
  yes: string;
  no: string;
  label: string;
}) {
  const current = value === null ? "any" : value ? "yes" : "no";
  return (
    <Chip.Group
      value={current}
      onChange={(next) => onChange(next === "any" ? null : next === "yes")}
    >
      <Group gap={6} aria-label={label}>
        <Chip value="any" size="xs" variant="outline">
          Any
        </Chip>
        <Chip value="yes" size="xs" variant="outline">
          {yes}
        </Chip>
        <Chip value="no" size="xs" variant="outline">
          {no}
        </Chip>
      </Group>
    </Chip.Group>
  );
}

const AVAILABILITY_LABELS: Record<string, string> = {
  scored: "Available Now",
  pending: "Coming Soon",
  unavailable: "None Listed",
};

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
    canPublish && onPublish !== undefined && !matchesShared && (filtersActive || sharedActive);

  const setField = <K extends keyof OverviewFilterState>(key: K, value: OverviewFilterState[K]) =>
    onChange({ ...filters, [key]: value });

  const removePill = (key: FilterPillKey) =>
    setField(key, DEFAULT_OVERVIEW_FILTERS[key] as OverviewFilterState[typeof key]);

  return (
    <Stack gap="xs">
      <Group gap="xs" wrap="wrap" align="center">
        {/* Search and Filters share an edge: one control, not a floating pill. */}
        <Group gap={0} wrap="nowrap" style={{ flex: 1, minWidth: 240, maxWidth: 460 }}>
          <TextInput
            aria-label="search listings"
            placeholder="Search name or address"
            leftSection={<IconSearch size={14} stroke={1.5} />}
            value={filters.query ?? ""}
            onChange={(e) => setField("query", e.currentTarget.value || null)}
            size="xs"
            style={{ flex: 1, minWidth: 0 }}
            styles={{ input: { borderStartEndRadius: 0, borderEndEndRadius: 0 } }}
          />
          <Button
            variant="default"
            size="xs"
            leftSection={<IconFilter size={14} stroke={1.5} />}
            onClick={toggle}
            aria-expanded={opened}
            styles={{ root: { borderStartStartRadius: 0, borderEndStartRadius: 0, marginInlineStart: -1 } }}
          >
            Filters{activeCount > 0 ? ` (${activeCount})` : ""}
          </Button>
        </Group>

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
          <Text size="xs" c="dimmed" aria-label="Filter result summary">
            {visibleCount} visible · {filteredOut} filtered out
          </Text>
        )}
      </Group>

      <Collapse expanded={opened}>
        <Paper withBorder radius="md" p="md">
          <SimpleGrid cols={{ base: 1, xs: 2, md: 3, lg: 4 }} spacing="lg" verticalSpacing="md">
            <Section label="Score">
              <Range
                label="score"
                min={filters.minScore}
                max={filters.maxScore}
                onMin={(next) => setField("minScore", next)}
                onMax={(next) => setField("maxScore", next)}
                step={0.5}
              />
            </Section>

            <Section label="Rent / Month">
              <Range
                label="rent"
                prefix="$"
                min={filters.minRent}
                max={filters.maxRent}
                onMin={(next) => setField("minRent", next)}
                onMax={(next) => setField("maxRent", next)}
                step={50}
              />
            </Section>

            <Section label="All-In Monthly">
              <NumberInput
                aria-label="maximum all-in monthly"
                placeholder="at most"
                prefix="$"
                step={50}
                min={0}
                size="xs"
                value={filters.maxAllIn ?? ""}
                onChange={(next) =>
                  setField("maxAllIn", typeof next === "number" ? next : null)
                }
              />
            </Section>

            <Section label="Square Feet">
              <Range
                label="square feet"
                min={filters.minSqft}
                max={filters.maxSqft}
                onMin={(next) => setField("minSqft", next)}
                onMax={(next) => setField("maxSqft", next)}
                step={50}
              />
            </Section>

            <Section label="Bedrooms">
              <Range
                label="bedrooms"
                min={filters.minBeds}
                max={filters.maxBeds}
                onMin={(next) => setField("minBeds", next)}
                onMax={(next) => setField("maxBeds", next)}
              />
            </Section>

            <Section label="Bathrooms">
              <Range
                label="bathrooms"
                min={filters.minBaths}
                max={filters.maxBaths}
                onMin={(next) => setField("minBaths", next)}
                onMax={(next) => setField("maxBaths", next)}
                step={0.5}
              />
            </Section>

            <Section label="City">
              <Toggles
                label="City"
                values={cities}
                selected={filters.cities}
                onChange={(next) => setField("cities", next)}
                labelFor={(value) => value}
              />
            </Section>

            <Section label="Availability">
              <Stack gap={6}>
                <Toggles
                  label="Availability"
                  values={["scored", "pending", "unavailable"]}
                  selected={filters.availabilities}
                  onChange={(next) =>
                    setField("availabilities", next as OverviewFilterState["availabilities"])
                  }
                  labelFor={(value) => AVAILABILITY_LABELS[value] ?? titleCase(value)}
                />
                <DatePickerInput
                  aria-label="available by"
                  placeholder="Available by — any date"
                  size="xs"
                  clearable
                  value={filters.availableBy ? new Date(filters.availableBy) : null}
                  onChange={(value) =>
                    setField(
                      "availableBy",
                      value ? new Date(value as unknown as string).toISOString().slice(0, 10) : null,
                    )
                  }
                />
              </Stack>
            </Section>

            <Section label="Status">
              <Toggles
                label="Status"
                values={["undecided", ...INTEREST_STATUSES]}
                selected={filters.statuses}
                onChange={(next) => setField("statuses", next as StatusFilter[])}
                labelFor={(value) =>
                  value === "undecided" ? "Undecided" : interestLabel(value as StatusFilter as never)
                }
              />
            </Section>

            <Section label="Visited">
              <TriState
                label="Visited"
                value={filters.visited}
                onChange={(next) => setField("visited", next)}
                yes="Visited"
                no="Not Yet"
              />
            </Section>

            <Section label="Laundry">
              <Toggles
                label="Laundry"
                values={LAUNDRY_VALUES}
                selected={filters.laundry}
                onChange={(next) => setField("laundry", next)}
              />
            </Section>

            <Section label="Parking">
              <Toggles
                label="Parking"
                values={PARKING_VALUES}
                selected={filters.parking}
                onChange={(next) => setField("parking", next)}
              />
            </Section>

            <Section label="Pets">
              <Toggles
                label="Pets"
                values={PETS_VALUES}
                selected={filters.pets}
                onChange={(next) => setField("pets", next)}
              />
            </Section>

            <Section label="Cooling">
              <Toggles
                label="Cooling"
                values={COOLING_VALUES}
                selected={filters.cooling}
                onChange={(next) => setField("cooling", next)}
              />
            </Section>

            <Section label="Dishwasher">
              <TriState
                label="Dishwasher"
                value={filters.dishwasher}
                onChange={(next) => setField("dishwasher", next)}
                yes="Yes"
                no="No"
              />
            </Section>
          </SimpleGrid>

          <Group gap="sm" mt="md" pt="sm" style={{ borderTop: "1px solid var(--mantine-color-default-border)" }}>
            <Text size="sm" c="dimmed">
              <Text span fw={600} c="var(--mantine-color-text)">
                {visibleCount}
              </Text>{" "}
              visible · {filteredOut} filtered out
            </Text>
            <Box style={{ flex: 1 }} />
            {filtersActive && (
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
                label="Members start from this view; they can still deviate locally."
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
        </Paper>
      </Collapse>
    </Stack>
  );
}
