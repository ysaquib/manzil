// The checklist runtime (VC-3, DESIGN §9.7).
//
// The load-bearing behaviour here is scope: a section is Property-scoped or
// Floor-Plan-scoped, and **the unit switcher exists only where it applies**.
// The dangerous failure on a tour is not a missing answer but an answer filed
// against the wrong unit, so the switcher disappears rather than sitting there
// implying a choice that isn't being made.
import {
  Badge,
  Box,
  Card,
  Group,
  Progress,
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";
import { useMemo, useState } from "react";

import { useAuth } from "../../auth/useAuth";
import { useMembers } from "../collaboration/api";
import { memberColor } from "../collaboration/memberColors";
import { useListings } from "../listings/api";
import { unitGroupLabel } from "../listings/unitGroups";
import {
  isOptimisticEntry,
  useSaveVisitEntries,
  useVisitCustomItems,
  useVisitEntries,
  useVisitEntryConflicts,
  useVisitFeeProposals,
  useVisitTemplate,
} from "./api";
import { ConflictPicker } from "./ConflictPicker";
import { VisitMoneyLedger } from "./VisitMoneyLedger";
import { SyncBadge } from "./SyncBadge";
import {
  currentAnswer,
  flaggedBy,
  indexEntries,
  isAnswered,
  isFlag,
  mergeCustomItems,
  meanRating,
  ownerFor,
  progressFor,
  teamAnswers,
  unitFor,
} from "./entries";
import type { Visit, VisitEntryConflict, VisitItem, VisitUnit } from "./types";
import { VisitByline } from "./VisitByline";
import { ControlForItem } from "./VisitControls";
import { VisitPresence } from "./VisitPresence";
import { useGhostMode } from "../admin/useGhostMode";
import { useVisitPresence } from "./usePresence";
import classes from "./VisitChecklist.module.css";
import { groupIntoSections, sectionTitle, type Tier } from "./visitState";

function UnitSwitcher({
  units,
  activeUnitId,
  onChange,
}: {
  units: VisitUnit[];
  activeUnitId: string | null;
  onChange: (id: string) => void;
}) {
  return (
    <ScrollArea type="never">
      <Group gap={6} wrap="nowrap" py={4}>
        {units.map((unit) => {
          const active = unit.id === activeUnitId;
          return (
            <Badge
              key={unit.id}
              component="button"
              type="button"
              variant={active ? "filled" : "outline"}
              color={unit.floor_plan_id ? "gray" : "teal"}
              radius="sm"
              size="lg"
              className={classes.unitChip}
              style={unit.floor_plan_id ? undefined : { borderStyle: active ? "solid" : "dashed" }}
              onClick={() => onChange(unit.id)}
              aria-pressed={active}
            >
              {unit.label}
            </Badge>
          );
        })}
      </Group>
    </ScrollArea>
  );
}

export function VisitChecklist({
  visit,
  readOnly,
  restrictTo,
}: {
  visit: Visit;
  readOnly?: boolean;
  /** Section keys to show. Used before a tour starts, when only prep is open. */
  restrictTo?: string[];
}) {
  const { session } = useAuth();
  const userId = session?.user.id ?? null;
  const membersQuery = useMembers(visit.hunt_id);
  const members = useMemo(() => membersQuery.data ?? [], [membersQuery.data]);
  const units = useMemo(
    () => [...(visit.visit_units ?? [])].sort((a, b) => a.display_order - b.display_order),
    [visit.visit_units],
  );

  const [tier, setTier] = useState<Tier>("standard");
  const [activeUnitId, setActiveUnitId] = useState<string | null>(units[0]?.id ?? null);
  const [activeSection, setActiveSection] = useState<string | null>(null);

  const templateQuery = useVisitTemplate(visit.template_version);
  const customQuery = useVisitCustomItems(visit.id);
  const entriesQuery = useVisitEntries(visit.id);
  const conflictsQuery = useVisitEntryConflicts(visit.id);
  const proposalsQuery = useVisitFeeProposals(visit.id);
  // The Listing this Property has in the Hunt — where a confirmed figure would
  // go. A Property with no active Listing simply has no ledger.
  const listingsQuery = useListings(visit.hunt_id);
  const listing = listingsQuery.data?.find(
    (candidate) => candidate.property_id === visit.property_id,
  );
  const saveEntries = useSaveVisitEntries(visit.id, userId ?? null, (entry) => {
    const item = items.find((candidate) => candidate.key === entry.item_key);
    return item ? ownerFor(item, userId ?? null) : null;
  });

  const items = useMemo(
    () =>
      mergeCustomItems(
        (templateQuery.data ?? []) as VisitItem[],
        customQuery.data ?? [],
        visit.template_version,
      ),
    [templateQuery.data, customQuery.data, visit.template_version],
  );
  const sections = useMemo(() => {
    const all = groupIntoSections(items, tier);
    return restrictTo ? all.filter((section) => restrictTo.includes(section.key)) : all;
  }, [items, tier, restrictTo]);
  const entries = entriesQuery.data ?? [];
  const index = useMemo(() => indexEntries(entries), [entries]);

  const currentSectionKey = activeSection ?? sections[0]?.key ?? null;
  // A ghost watches the tour without joining it. `isGhost` is undefined until
  // membership is known, and the `!== false` test is deliberate: observe until
  // proven a member, so a slow membership read can never flash an admin onto
  // somebody else's tour.
  const { isGhost } = useGhostMode(visit.hunt_id);
  const present = useVisitPresence(
    visit.id,
    userId ?? undefined,
    currentSectionKey,
    isGhost !== false,
  );
  const section = sections.find((candidate) => candidate.key === currentSectionKey);
  const unitScoped = section?.hasUnitScoped ?? false;
  // A section can hold both scopes (Building history asks about the building and
  // about this unit). A blanket "recording into 4B" would be false for half of
  // it, so a mixed section says so and each item carries its own tag.
  const mixed = Boolean(section?.hasUnitScoped && section?.hasPropertyScoped);
  const activeUnit = units.find((unit) => unit.id === activeUnitId) ?? null;

  function save(item: VisitItem, patch: { value?: unknown; answer_text?: string | null }) {
    const unitId = unitFor(item, activeUnitId);
    // A unit-scoped item with no unit selected has nowhere to go; the API would
    // reject it, so don't send it.
    if (item.scope === "unit" && !unitId) return;
    const previous = currentAnswer(index, item, activeUnitId, userId);
    saveEntries.mutate([
      {
        item_key: item.key,
        is_custom: item.isCustom ?? false,
        visit_unit_id: unitId,
        // An optimistic row has no server identity, so it cannot be claimed as
        // a parent — doing so would either fail the foreign key or, worse,
        // manufacture a fork against a row that never existed. Answering the
        // same item twice offline is one queued write following another, which
        // is not a conflict.
        prev_entry_id: previous && !isOptimisticEntry(previous) ? previous.id : null,
        ...patch,
      },
    ]);
  }

  /**
   * Collapse a fork by appending the chosen branch's value as a new answer
   * descending from it. The same write shape as any other answer — resolution
   * needs no special route, which is what append-only buys.
   */
  function resolveConflict(branch: VisitEntryConflict) {
    saveEntries.mutate([
      {
        item_key: branch.item_key,
        is_custom: branch.is_custom,
        visit_unit_id: branch.visit_unit_id,
        prev_entry_id: branch.id,
        value: branch.value,
        answer_text: branch.answer_text,
        note: branch.note,
      },
    ]);
  }

  if (templateQuery.isLoading || entriesQuery.isLoading) {
    return (
      <Card>
        <Text size="sm" c="dimmed">
          Loading the checklist…
        </Text>
      </Card>
    );
  }

  return (
    <Stack gap="md">
      <ConflictPicker
        conflicts={conflictsQuery.data ?? []}
        items={items}
        units={units}
        members={members}
        viewerId={userId ?? null}
        onResolve={resolveConflict}
      />
      <Card padding="sm">
        <Stack gap="sm">
          <Group justify="space-between" gap="sm" wrap="nowrap">
            <VisitPresence present={present} members={members} />
            <SyncBadge />
          </Group>
          <Group justify="space-between" gap="sm" wrap="wrap">
            <SegmentedControl
              size="xs"
              value={tier}
              onChange={(value) => setTier(value as Tier)}
              data={[
                { value: "quick", label: "Quick" },
                { value: "standard", label: "Standard" },
                { value: "thorough", label: "Thorough" },
              ]}
            />
            <Text size="xs" c="dimmed">
              {tier === "quick"
                ? "Only what you'd regret missing"
                : tier === "standard"
                  ? "A normal 30-minute tour"
                  : "Everything in the checklist"}
            </Text>
          </Group>

          {/* The switcher exists only where it applies. */}
          {unitScoped && units.length > 0 && (
            <UnitSwitcher units={units} activeUnitId={activeUnitId} onChange={setActiveUnitId} />
          )}

          <Group gap={6} className={classes.scopeBar}>
            <IconInfoCircle size={13} />
            {mixed ? (
              <Text size="xs">
                Mixed — some answers are per unit, some once for the property.{" "}
                <strong>Each item says which.</strong>
              </Text>
            ) : unitScoped ? (
              activeUnit ? (
                <Text size="xs">
                  Recording into <strong>{activeUnit.label}</strong>
                  {" · "}
                  {unitGroupLabel(activeUnit.beds, activeUnit.baths)}
                </Text>
              ) : (
                <Text size="xs">Add a unit to answer this section</Text>
              )
            ) : (
              <Text size="xs">
                Property-level — recorded <strong>once for this visit</strong>, not per unit
              </Text>
            )}
          </Group>
        </Stack>
      </Card>

      <ScrollArea type="never">
        <Group gap={6} wrap="nowrap" py={2}>
          {sections.map((candidate) => {
            const progress = progressFor(
              candidate.items,
              index,
              candidate.hasUnitScoped ? activeUnitId : null,
              userId,
            );
            const active = candidate.key === currentSectionKey;
            return (
              <Badge
                key={candidate.key}
                component="button"
                type="button"
                variant={active ? "filled" : "outline"}
                color={progress.answered === progress.total ? "green" : "gray"}
                radius="sm"
                size="lg"
                className={classes.sectionChip}
                onClick={() => setActiveSection(candidate.key)}
                aria-pressed={active}
              >
                {sectionTitle(candidate.key)} {progress.answered}/{progress.total}
              </Badge>
            );
          })}
        </Group>
      </ScrollArea>

      {section && (
        <Card>
          <Stack gap="xs">
            <Group justify="space-between" align="center">
              <Text fw={600} ff="var(--mantine-font-family-headings)" size="md">
                {sectionTitle(section.key)}
              </Text>
              <Badge variant="light" color="gray" radius="sm">
                {mixed ? "Mixed" : section.hasUnitScoped ? (activeUnit?.label ?? "no unit") : "Whole property"}
              </Badge>
            </Group>

            <Progress
              size="xs"
              value={
                (progressFor(section.items, index, unitScoped ? activeUnitId : null, userId)
                  .answered /
                  Math.max(section.items.length, 1)) *
                100
              }
            />

            <Stack gap={0} mt="xs">
              {section.items.map((item) => {
                const entry = currentAnswer(index, item, activeUnitId, userId);
                const answered = isAnswered(item, entry);
                const team = teamAnswers(entries, item, activeUnitId);
                const mean = meanRating(team);
                const blocked = item.scope === "unit" && !activeUnitId;
                return (
                  <Box key={item.key} className={classes.itemRow} data-answered={answered}>
                    <Box className={classes.itemLabel}>
                      <Group gap={6} wrap="wrap">
                        <Text size="sm">{item.label}</Text>
                        {item.is_critical && (
                          <Badge color="yellow" variant="light" size="xs" radius="sm">
                            Critical
                          </Badge>
                        )}
                        {item.isCustom && (
                          <Badge
                            color="teal"
                            variant="outline"
                            size="xs"
                            radius="sm"
                            style={{ borderStyle: "dashed" }}
                          >
                            Custom
                          </Badge>
                        )}
                        {mixed && (
                          <Tooltip
                            label={
                              item.scope === "unit"
                                ? "Answered once per unit"
                                : "Answered once for the property"
                            }
                          >
                            <Badge color="gray" variant="outline" size="xs" radius="sm">
                              {item.scope === "unit"
                                ? (activeUnit?.label ?? "per unit")
                                : "Whole property"}
                            </Badge>
                          </Tooltip>
                        )}
                        {ownerFor(item, userId) && (
                          <Tooltip label="Your own answer — everyone records their own">
                            <Badge color="grape" variant="light" size="xs" radius="sm">
                              Yours
                            </Badge>
                          </Tooltip>
                        )}
                      </Group>
                      {item.help && (
                        <Text size="xs" c="dimmed">
                          {item.help}
                        </Text>
                      )}
                      {isFlag(item)
                        ? (() => {
                            // Red flags are judgements, so they are tallied per
                            // member rather than merged — a lone flag is
                            // information, not noise.
                            const flags = flaggedBy(team);
                            const names = flags.map(
                              (id) =>
                                membersQuery.data?.find((m) => m.user_id === id)
                                  ?.display_name ?? "a member",
                            );
                            const total = membersQuery.data?.length ?? 0;
                            return flags.length > 0 ? (
                              <Text size="xs" c="dimmed">
                                Flagged by {names.join(", ")}
                                {total > 1 ? ` · ${flags.length} of ${total}` : ""}
                              </Text>
                            ) : null;
                          })()
                        : mean !== null &&
                          team.length > 1 && (
                            <Group gap={6} wrap="wrap">
                              <Text size="xs" c="dimmed">
                                Team average {mean} ·
                              </Text>
                              {team.map((answer) => {
                                const member = members.find(
                                  (candidate) => candidate.user_id === answer.owner_user_id,
                                );
                                return (
                                  <Tooltip
                                    key={answer.id}
                                    label={`${member?.display_name ?? "A member"} rated ${String(answer.value)}`}
                                  >
                                    <Text size="xs" c="dimmed" span>
                                      <span
                                        aria-hidden
                                        className={classes.memberDot}
                                        style={{
                                          backgroundColor: memberColor(member?.color ?? null),
                                        }}
                                      />
                                      {String(answer.value)}
                                    </Text>
                                  </Tooltip>
                                );
                              })}
                            </Group>
                          )}
                      {/* Shared answers say who wrote them; an Impression is
                          yours by construction, so a byline would be noise. */}
                      {entry && ownerFor(item, userId) === null && (
                        <VisitByline entry={entry} members={members} viewerId={userId} />
                      )}
                    </Box>
                    <Box className={classes.itemControl}>
                      <ControlForItem
                        item={item}
                        entry={entry}
                        disabled={blocked}
                        readOnly={readOnly}
                        onSave={(patch) => save(item, patch)}
                      />
                    </Box>
                  </Box>
                );
              })}
            </Stack>
          </Stack>
        </Card>
      )}

      {/* The ledger belongs to the Money section: it is the same conversation
          with the agent, and putting it anywhere else would separate the
          figures from the questions that produce them. */}
      {currentSectionKey === "money" && (
        <VisitMoneyLedger
          visitId={visit.id}
          listing={listing}
          proposals={proposalsQuery.data ?? []}
          activeUnit={activeUnit}
          readOnly={readOnly}
        />
      )}
    </Stack>
  );
}
