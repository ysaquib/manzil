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
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconInfoCircle } from "@tabler/icons-react";
import { useMemo, useState } from "react";

import { useAuth } from "../../auth/useAuth";
import { useHuntContributors, useMembers } from "../collaboration/api";
import { contributorColor, contributorDisplayName } from "../collaboration/memberDisplay";
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
import { toneFor } from "./statusColors";
import type {
  Visit,
  VisitEditMode,
  VisitEntryConflict,
  VisitItem,
  VisitUnit,
} from "./types";
import { VisitInsights } from "./VisitInsights";
import { VisitItemNote } from "./VisitItemNote";
import {
  PhaseBar,
  SectionHeading,
  SectionPicker,
  SectionRail,
  SectionSteps,
} from "./VisitSectionNav";
import { VisitByline } from "./VisitByline";
import { ControlForItem } from "./VisitControls";
import { VisitPresence } from "./VisitPresence";
import { useGhostMode } from "../admin/useGhostMode";
import { useVisitPresence } from "./usePresence";
import classes from "./VisitChecklist.module.css";
import { groupIntoSections, neighbours, sectionTitle, type Tier } from "./visitState";

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
  mode = "live",
  restrictTo,
}: {
  visit: Visit;
  /** `record` for a finished tour, `void` for a cancelled one (VC-12). */
  mode?: VisitEditMode;
  /** Section keys to show. Used before a tour starts, when only prep is open. */
  restrictTo?: string[];
}) {
  const { session } = useAuth();
  const userId = session?.user.id ?? null;
  const membersQuery = useMembers(visit.hunt_id);
  const members = useMemo(() => membersQuery.data ?? [], [membersQuery.data]);
  const contributorsQuery = useHuntContributors(visit.hunt_id);
  const contributors = useMemo(
    () => contributorsQuery.data ?? [],
    [contributorsQuery.data],
  );
  const units = useMemo(
    () => [...(visit.visit_units ?? [])].sort((a, b) => a.display_order - b.display_order),
    [visit.visit_units],
  );

  // Which panes exist is a *rendering* decision, not just a styling one: the
  // rail and the phase bar are the same list, so leaving both in the DOM and
  // hiding one with CSS would read it twice to a screen reader and give every
  // section two buttons with the same name. Only one is ever mounted.
  const wideEnoughForRail = useMediaQuery("(min-width: 82em)") ?? false;
  const wideEnoughForInsights = useMediaQuery("(min-width: 62em)") ?? false;

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

  function save(
    item: VisitItem,
    patch: { value?: unknown; answer_text?: string | null; note?: string | null },
  ) {
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

  /** A section's progress, in the scope it is actually answered in. */
  const sectionProgress = (candidate: (typeof sections)[number]) =>
    progressFor(candidate.items, index, candidate.hasUnitScoped ? activeUnitId : null, userId);

  const { previous, next } = neighbours(sections, currentSectionKey);

  // Questions nobody has answered, across the whole checklist rather than this
  // section — "what did we forget to ask" is never a per-room question.
  const openQuestions = useMemo(
    () =>
      items.filter(
        (item) =>
          item.kind === "question" &&
          !isAnswered(item, currentAnswer(index, item, activeUnitId, userId)),
      ),
    [items, index, activeUnitId, userId],
  );

  if (templateQuery.isLoading || entriesQuery.isLoading) {
    return (
      <Card>
        <Text size="sm" c="dimmed">
          Loading the checklist…
        </Text>
      </Card>
    );
  }

  const scopeLabel = mixed
    ? "Mixed"
    : section?.hasUnitScoped
      ? (activeUnit?.label ?? "no unit")
      : "Whole property";

  return (
    <Stack gap="md">
      <ConflictPicker
        conflicts={conflictsQuery.data ?? []}
        items={items}
        units={units}
        contributors={contributors}
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

      {/* Three panes on a desktop, one on a phone. The rail and the insight
          column drop out below their breakpoints, which is why the phone
          layout needs no separate component: it is this one, narrower. */}
      <Box
        className={classes.layout}
        data-panes={
          wideEnoughForRail ? "three" : wideEnoughForInsights ? "two" : "one"
        }
      >
        {wideEnoughForRail && (
          <Box className={classes.railPane}>
            <SectionRail
              sections={sections}
              current={currentSectionKey}
              onSelect={setActiveSection}
              progressFor={sectionProgress}
            />
          </Box>
        )}

        <Stack gap="md" className={classes.mainPane}>
          {/* The compact navigation: five phases that fit, and the section name
              as the button onto the full list. Hidden once the rail is up. */}
          {!wideEnoughForRail && (
          <Card padding={0} className={classes.compactNav}>
            <PhaseBar
              sections={sections}
              current={currentSectionKey}
              onSelect={setActiveSection}
              progressFor={sectionProgress}
            />
            <Box px="sm">
              <SectionPicker
                sections={sections}
                current={currentSectionKey}
                onSelect={setActiveSection}
                progressFor={sectionProgress}
              />
            </Box>
          </Card>
          )}

      {section && (
        <Card>
          <Stack gap="xs">
            <SectionHeading
              title={sectionTitle(section.key)}
              scopeLabel={scopeLabel}
              progress={sectionProgress(section)}
              showTitle={wideEnoughForRail}
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
                          <Badge
                            color={toneFor("critical").color}
                            variant={toneFor("critical").variant}
                            size="xs"
                            radius="sm"
                          >
                            Critical
                          </Badge>
                        )}
                        {item.isCustom && (
                          <Badge
                            color={toneFor("custom").color}
                            variant={toneFor("custom").variant}
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
                            <Badge
                              color={toneFor("personal").color}
                              variant={toneFor("personal").variant}
                              size="xs"
                              radius="sm"
                            >
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
                                contributorDisplayName(
                                  contributors.find((contributor) => contributor.user_id === id),
                                ),
                            );
                            const total = membersQuery.data?.length ?? 0;
                            const currentIds = new Set(
                              membersQuery.data?.map((member) => member.user_id) ?? [],
                            );
                            const currentFlags = flags.filter((id) => currentIds.has(id)).length;
                            return flags.length > 0 ? (
                              <Text size="xs" c="dimmed">
                                Flagged by {names.join(", ")}
                                {total > 1 && currentFlags > 0
                                  ? ` · ${currentFlags} of ${total} current members`
                                  : ""}
                              </Text>
                            ) : null;
                          })()
                        : mean !== null &&
                          team.length > 1 && (
                            <Group gap={6} wrap="wrap">
                              <Text size="xs" c="dimmed">
                                Visit average {mean} ·
                              </Text>
                              {team.map((answer) => {
                                const contributor = contributors.find(
                                  (candidate) => candidate.user_id === answer.owner_user_id,
                                );
                                return (
                                  <Tooltip
                                    key={answer.id}
                                    label={`${contributorDisplayName(contributor)} rated ${String(answer.value)}`}
                                  >
                                    <Text size="xs" c="dimmed" span>
                                      <span
                                        aria-hidden
                                        className={classes.memberDot}
                                        style={{
                                          backgroundColor: contributorColor(contributor),
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
                        <VisitByline
                          entry={entry}
                          contributors={contributors}
                          viewerId={userId}
                        />
                      )}
                      {/* VC-15: the 249th thought. A tri-state cannot say why a
                          check failed and a 2-out-of-5 cannot say what was
                          wrong with the counter. */}
                      <VisitItemNote
                        entry={entry}
                        label={item.label}
                        mode={mode}
                        onSave={(note) => save(item, { note })}
                      />
                    </Box>
                    <Box className={classes.itemControl}>
                      <ControlForItem
                        item={item}
                        entry={entry}
                        disabled={blocked}
                        mode={mode}
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
          readOnly={mode !== "live"}
        />
      )}

          {/* Nobody tours a flat by jumping: the common path is the template's
              own order, two taps from the foot of the section you just did. */}
          <SectionSteps previous={previous} next={next} onSelect={setActiveSection} />
        </Stack>

        {wideEnoughForInsights && (
        <Box className={classes.insightPane}>
          {section && (
            <VisitInsights
              visit={visit}
              items={section.items}
              entries={entries}
              activeUnitId={section.hasUnitScoped ? activeUnitId : null}
              contributors={contributors}
              viewerId={userId ?? null}
              answered={sectionProgress(section).answered}
              total={sectionProgress(section).total}
              openQuestions={openQuestions}
              defectCount={0}
            />
          )}
        </Box>
        )}
      </Box>
    </Stack>
  );
}
