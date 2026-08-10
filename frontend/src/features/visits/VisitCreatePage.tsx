// Create a Visit (VC-2, DESIGN §13.2): property → plans → units.
//
// Prep is not a step here. Pre-visit is a *state*, not a screen (DESIGN §9.7) —
// a planned Visit is one whose tour has not started — so creating navigates to
// the Visit itself, which *is* the prep page.
//
// It used to be declared as a fourth `Stepper.Step` with no children, as a
// label for that fact. Mantine resolves content by active index
// (`_children[active].props.children`), so the moment anything advanced the
// stepper to it the step rendered undefined content and the page threw. A step
// that must never be reached is not a step; the three real ones are the flow,
// and the sentence below the stepper does the explaining instead.
import {
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Checkbox,
  Group,
  NumberInput,
  Select,
  Stack,
  Stepper,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconArrowLeft, IconPlus, IconX } from "@tabler/icons-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../../lib/apiClient";
import { isDemo } from "../../lib/demo";
import { useListings } from "../listings/api";
import type { FloorPlan, Listing } from "../listings/types";
import { unitGroupKey, unitGroupLabel } from "../listings/unitGroups";
import { useCreateVisit } from "./api";
import type { DraftUnit } from "./types";

const DESCRIBE_IT = "__describe__";

let localCounter = 0;
const nextLocalId = () => `draft-${(localCounter += 1)}`;

/** Current Floor Plans grouped by derived Unit Group, in bed/bath order. */
function planGroups(listing: Listing | undefined) {
  if (!listing) return [];
  const groups = new Map<string, { beds: number; baths: number; plans: FloorPlan[] }>();
  for (const plan of listing.property.floor_plans) {
    if (plan.is_current === false) continue;
    const key = unitGroupKey(plan.beds, plan.baths);
    const bucket = groups.get(key);
    if (bucket) bucket.plans.push(plan);
    else groups.set(key, { beds: plan.beds, baths: plan.baths, plans: [plan] });
  }
  return [...groups.entries()]
    .map(([key, value]) => ({ key, ...value }))
    .sort((a, b) => a.beds - b.beds || a.baths - b.baths);
}

function money(plan: FloorPlan): string {
  if (plan.rent_min == null) return "rent unknown";
  return `from $${plan.rent_min.toLocaleString()}`;
}

function availability(plan: FloorPlan): string {
  if (plan.available_units == null) return "availability unknown";
  return plan.available_units === 0 ? "none listed" : `${plan.available_units} available`;
}

export function VisitCreatePage() {
  const { huntId = "" } = useParams();
  const navigate = useNavigate();
  const isCompact = useMediaQuery("(max-width: 48em)") ?? false;
  const listingsQuery = useListings(huntId);
  const createVisit = useCreateVisit(huntId);

  // demo-guarded: useCreateVisit — `submit()` awaits the response and navigates
  // to `visit.id`. A demo write resolves with nothing, so that read throws from
  // inside a `void submit()` click handler, unhandled. A synthetic id is not the
  // answer either: it would route the visitor to a Visit that does not exist.
  // The demo shows the Hunt's existing Visits instead, and says so here.
  const demo = isDemo();

  const [step, setStep] = useState(0);
  const [propertyId, setPropertyId] = useState<string | null>(null);
  const [selectedPlanIds, setSelectedPlanIds] = useState<string[]>([]);
  const [units, setUnits] = useState<DraftUnit[]>([]);
  const [adding, setAdding] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [newWhat, setNewWhat] = useState<string | null>(null);
  const [newBeds, setNewBeds] = useState<number | string>(2);
  const [newBaths, setNewBaths] = useState<number | string>(1);

  const listings = listingsQuery.data ?? [];
  const listing = listings.find((row) => row.property_id === propertyId);
  const groups = useMemo(() => planGroups(listing), [listing]);
  const plansById = useMemo(() => {
    const map = new Map<string, FloorPlan>();
    for (const group of groups) for (const plan of group.plans) map.set(plan.id, plan);
    return map;
  }, [groups]);

  // The property picker only offers properties already in this hunt: a visit to
  // somewhere with no Listing has nothing to check the agent's claims against.
  const propertyOptions = useMemo(
    () =>
      listings
        .map((row) => ({
          value: row.property_id,
          label: row.property.name,
          address: row.property.canonical_address,
        }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [listings],
  );

  function togglePlan(plan: FloorPlan, checked: boolean) {
    setSelectedPlanIds((previous) =>
      checked ? [...previous, plan.id] : previous.filter((id) => id !== plan.id),
    );
    setUnits((previous) => {
      if (checked) {
        // Ticking a plan pre-seeds a unit to name on site — the number is never
        // known in advance (DESIGN §9.7).
        if (previous.some((unit) => unit.floorPlanId === plan.id && !unit.custom)) return previous;
        return [
          ...previous,
          {
            localId: nextLocalId(),
            label: "",
            floorPlanId: plan.id,
            planName: plan.plan_name,
            beds: plan.beds,
            baths: plan.baths,
            custom: false,
          },
        ];
      }
      return previous.filter((unit) => unit.floorPlanId !== plan.id || unit.custom);
    });
  }

  function addUnit() {
    const label = newLabel.trim();
    if (!label) return;
    if (units.some((unit) => unit.label.trim().toLowerCase() === label.toLowerCase())) return;
    if (newWhat && newWhat !== DESCRIBE_IT) {
      const plan = plansById.get(newWhat);
      if (!plan) return;
      setUnits((previous) => [
        ...previous,
        {
          localId: nextLocalId(),
          label,
          floorPlanId: plan.id,
          planName: plan.plan_name,
          beds: plan.beds,
          baths: plan.baths,
          custom: true,
        },
      ]);
    } else {
      setUnits((previous) => [
        ...previous,
        {
          localId: nextLocalId(),
          label,
          floorPlanId: null,
          planName: null,
          beds: Number(newBeds) || 0,
          baths: Number(newBaths) || 0,
          custom: true,
        },
      ]);
    }
    setNewLabel("");
    setAdding(false);
  }

  function removeUnit(localId: string) {
    const unit = units.find((candidate) => candidate.localId === localId);
    setUnits((previous) => previous.filter((candidate) => candidate.localId !== localId));
    if (unit && !unit.custom && unit.floorPlanId) {
      setSelectedPlanIds((previous) => previous.filter((id) => id !== unit.floorPlanId));
    }
  }

  async function submit() {
    if (!propertyId || demo) return;
    const visit = await createVisit.mutateAsync({
      property_id: propertyId,
      units: units.map((unit, index) => ({
        // An unnamed unit still needs a label the API will accept; "Unit N" is a
        // placeholder the tourer renames on site.
        label: unit.label.trim() || `Unit ${index + 1}`,
        floor_plan_id: unit.floorPlanId,
        beds: unit.floorPlanId ? null : unit.beds,
        baths: unit.floorPlanId ? null : unit.baths,
        display_order: index,
      })),
    });
    void navigate(`/h/${huntId}/visits/${visit.id}`);
  }

  const duplicateLabel =
    newLabel.trim().length > 0 &&
    units.some((unit) => unit.label.trim().toLowerCase() === newLabel.trim().toLowerCase());

  return (
    <Stack gap="lg" maw={720}>
      <Group gap="xs">
        <Button
          component={Link}
          to={`/h/${huntId}/visits`}
          variant="subtle"
          size="compact-sm"
          leftSection={<IconArrowLeft size={14} />}
        >
          Visits
        </Button>
      </Group>
      <Title order={2}>New visit</Title>

      {/* Step descriptions wrap the stepper onto two rows on a phone and add
          nothing the label doesn't say, so they drop below `sm` — the same
          treatment the settings tab rail gives its subtitles. */}
      <Stepper
        active={step}
        onStepClick={setStep}
        size="sm"
        allowNextStepsSelect={false}
        orientation="horizontal"
      >
        <Stepper.Step label="Property" description={isCompact ? undefined : "Which building"}>
          <Stack gap="md" mt="lg">
            <Card>
              <Stack gap="sm">
                <Select
                  label="Property"
                  placeholder={
                    listingsQuery.isLoading ? "Loading your hunt…" : "Search your hunt…"
                  }
                  searchable
                  nothingFoundMessage="Nothing in this hunt matches"
                  data={propertyOptions}
                  value={propertyId}
                  onChange={(value) => {
                    setPropertyId(value);
                    setSelectedPlanIds([]);
                    setUnits([]);
                  }}
                  disabled={listingsQuery.isLoading}
                />
                <Text size="xs" c="dimmed">
                  Only properties already in this hunt. Touring somewhere new? Add the listing
                  first, so the visit has facts to check the agent against.
                </Text>
                {listing && (
                  <Text size="sm" c="dimmed">
                    {listing.property.canonical_address}
                  </Text>
                )}
              </Stack>
            </Card>
            <Group justify="flex-end">
              <Button disabled={!propertyId} onClick={() => setStep(1)}>
                Continue
              </Button>
            </Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Plans" description={isCompact ? undefined : "What you expect to see"}>
          <Stack gap="md" mt="lg">
            <Card>
              <Stack gap="xs">
                <Text size="xs" c="dimmed">
                  Unit Groups are derived from beds and baths; the plans inside them come from the
                  listing. Ticking one pre-seeds a unit you can name on site.
                </Text>
                {groups.length === 0 ? (
                  <Alert color="yellow" variant="light">
                    This listing has no current floor plans yet — you can still add units by hand
                    on the next step.
                  </Alert>
                ) : (
                  groups.map((group) => (
                    <Box key={group.key}>
                      <Group justify="space-between" mt="sm" mb={4}>
                        <Text size="sm" fw={600}>
                          {unitGroupLabel(group.beds, group.baths)}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {group.plans.length === 1 ? "1 plan" : `${group.plans.length} plans`}
                        </Text>
                      </Group>
                      <Stack gap={4}>
                        {group.plans.map((plan) => (
                          <Checkbox
                            key={plan.id}
                            checked={selectedPlanIds.includes(plan.id)}
                            onChange={(event) => togglePlan(plan, event.currentTarget.checked)}
                            label={
                              <Box>
                                <Text size="sm">{plan.plan_name}</Text>
                                <Text size="xs" c="dimmed">
                                  {[
                                    plan.sqft_min ? `${plan.sqft_min.toLocaleString()} sqft` : null,
                                    money(plan),
                                    availability(plan),
                                  ]
                                    .filter(Boolean)
                                    .join(" · ")}
                                </Text>
                              </Box>
                            }
                          />
                        ))}
                      </Stack>
                    </Box>
                  ))
                )}
              </Stack>
            </Card>
            <Group justify="space-between">
              <Button variant="subtle" onClick={() => setStep(0)}>
                Back
              </Button>
              <Button onClick={() => setStep(2)}>Continue</Button>
            </Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Units" description={isCompact ? undefined : "Doors you'll walk through"}>
          <Stack gap="md" mt="lg">
            <Card>
              <Stack gap="xs">
                <Group justify="space-between">
                  <Text size="sm" fw={600}>
                    Doors you'll walk through
                  </Text>
                  <Badge variant="light">
                    {units.length === 1 ? "1 unit" : `${units.length} units`}
                  </Badge>
                </Group>
                <Text size="xs" c="dimmed">
                  One per unit you expect to see. Numbers are yours to type — the app never knows
                  them in advance, so leaving one unnamed is fine.
                </Text>

                {units.length === 0 && (
                  <Text size="sm" c="dimmed" fs="italic" py="xs">
                    No units yet. Tick a plan on the previous step, or add one below.
                  </Text>
                )}

                <Stack gap={0}>
                  {units.map((unit, index) => (
                    <Group
                      key={unit.localId}
                      wrap="nowrap"
                      py="xs"
                      style={
                        index === 0
                          ? undefined
                          : { borderTop: "1px solid var(--mantine-color-default-border)" }
                      }
                    >
                      <TextInput
                        style={{ flex: 1 }}
                        placeholder="Name it on site"
                        aria-label={`Label for unit ${index + 1}`}
                        value={unit.label}
                        onChange={(event) => {
                          const label = event.currentTarget.value;
                          setUnits((previous) =>
                            previous.map((candidate) =>
                              candidate.localId === unit.localId
                                ? { ...candidate, label }
                                : candidate,
                            ),
                          );
                        }}
                      />
                      <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
                        <Text size="xs">
                          {unit.planName ?? unitGroupLabel(unit.beds, unit.baths)}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {unit.floorPlanId
                            ? unitGroupLabel(unit.beds, unit.baths)
                            : "not advertised"}
                        </Text>
                      </Stack>
                      {unit.custom && (
                        <Badge
                          variant="outline"
                          color="teal"
                          radius="sm"
                          style={{ borderStyle: "dashed", flex: "none" }}
                        >
                          Custom
                        </Badge>
                      )}
                      <Button
                        variant="subtle"
                        color="gray"
                        size="compact-sm"
                        aria-label={`Remove unit ${unit.label || index + 1}`}
                        onClick={() => removeUnit(unit.localId)}
                      >
                        <IconX size={14} />
                      </Button>
                    </Group>
                  ))}
                </Stack>

                {adding ? (
                  <Card withBorder mt="xs" bg="var(--mantine-color-default-hover)">
                    <Stack gap="sm">
                      <TextInput
                        label="What will you call it?"
                        placeholder='4B · or "the corner one"'
                        value={newLabel}
                        onChange={(event) => setNewLabel(event.currentTarget.value)}
                        error={duplicateLabel ? "This visit already has a unit with that name" : null}
                      />
                      <Select
                        label="What is it?"
                        placeholder="Pick a plan, or describe it"
                        data={[
                          ...[...plansById.values()].map((plan) => ({
                            value: plan.id,
                            label: `${plan.plan_name} — ${unitGroupLabel(plan.beds, plan.baths)}`,
                          })),
                          { value: DESCRIBE_IT, label: "Not one of these — describe it" },
                        ]}
                        value={newWhat}
                        onChange={setNewWhat}
                      />
                      {(newWhat === DESCRIBE_IT || plansById.size === 0) && (
                        <Group grow>
                          <NumberInput
                            label="Beds"
                            min={0}
                            max={20}
                            value={newBeds}
                            onChange={setNewBeds}
                          />
                          <NumberInput
                            label="Baths"
                            min={0}
                            max={20}
                            step={0.5}
                            value={newBaths}
                            onChange={setNewBaths}
                          />
                        </Group>
                      )}
                      <Group>
                        <Button
                          onClick={addUnit}
                          disabled={!newLabel.trim() || duplicateLabel || !newWhat}
                        >
                          Add unit
                        </Button>
                        <Button variant="subtle" onClick={() => setAdding(false)}>
                          Cancel
                        </Button>
                      </Group>
                    </Stack>
                  </Card>
                ) : (
                  <Button
                    variant="light"
                    mt="xs"
                    leftSection={<IconPlus size={16} />}
                    onClick={() => {
                      setAdding(true);
                      setNewWhat(plansById.size ? null : DESCRIBE_IT);
                    }}
                  >
                    Add another unit
                  </Button>
                )}
              </Stack>
            </Card>

            {demo && (
              <Alert color="yellow" title="Not available in the demo">
                Visits are collaborative records of a real tour, so the demo
                shows the ones already in this Hunt rather than letting you
                start another. Everything else on a Visit is browsable.
              </Alert>
            )}

            {createVisit.isError && (
              <Alert color="red" title="Couldn't create the visit">
                {createVisit.error instanceof ApiError
                  ? createVisit.error.message
                  : "Something went wrong."}
              </Alert>
            )}

            <Group justify="space-between">
              <Button variant="subtle" onClick={() => setStep(1)}>
                Back
              </Button>
              <Button
                onClick={() => void submit()}
                loading={createVisit.isPending}
                disabled={!propertyId || demo}
              >
                Create visit
              </Button>
            </Group>
          </Stack>
        </Stepper.Step>
      </Stepper>
    </Stack>
  );
}
