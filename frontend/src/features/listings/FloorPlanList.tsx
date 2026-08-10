// Floor Plan list for one Unit Group (P3-SC5, §9.4). Replaces the P1-11
// `FloorPlanPins` radio group: the card list is the comparison surface, the
// detail modal is the deep read on one plan, and the pin is a toggle on each
// card rather than a radio option.
//
// Pinning stays draft-only until the drawer's Save, exactly as before — the
// card and the modal footer both call the same `setDraftPin`.
import { Group, Stack, Text } from "@mantine/core";
import { useMemo } from "react";

import type { CatalogEntry } from "../rubric/api";
import { amenityCounts, floorPlanAmenities } from "./floorPlanAmenities";
import { FloorPlanCard } from "./FloorPlanCard";
import listClasses from "./FloorPlanList.module.css";
import { useListingDetailDraft } from "./ListingDetailDraft";
import type { PropertyImage } from "./api";
import type { Extraction, Override, Score } from "./types";
import { unitGroupLabel, type UnitGroupRow } from "./unitGroups";

const LEGEND: { state: string; glyph: string; word: string }[] = [
  { state: "confirmed", glyph: "✓", word: "confirmed" },
  { state: "advertised", glyph: "~", word: "advertised" },
  { state: "absent", glyph: "✕", word: "absent" },
  { state: "unknown", glyph: "?", word: "unknown" },
];

export interface FloorPlanListProps {
  group: UnitGroupRow;
  scores: Score[];
  catalog: CatalogEntry[];
  extractions: Extraction[];
  overrides: Override[];
  images: PropertyImage[];
  openPlanId: string | null;
  onOpenPlan: (planId: string) => void;
}

export function FloorPlanList({
  group,
  scores,
  catalog,
  extractions,
  overrides,
  images,
  openPlanId,
  onOpenPlan,
}: FloorPlanListProps) {
  const { draftPins, setDraftPin, saving } = useListingDetailDraft();

  const scoreByPlan = useMemo(
    () => new Map(scores.map((score) => [score.floor_plan_id, score])),
    [scores],
  );

  // Diagrams only: a Property photo must never stand in for a layout (§9.3).
  const diagramsByPlan = useMemo(() => {
    const byPlan = new Map<string, string[]>();
    for (const image of images) {
      if (image.kind !== "floor_plan_diagram") continue;
      for (const planId of image.floorPlanAssociations ?? []) {
        const urls = byPlan.get(planId) ?? [];
        urls.push(image.url);
        byPlan.set(planId, urls);
      }
    }
    return byPlan;
  }, [images]);

  const countsByPlan = useMemo(() => {
    const byPlan = new Map<string, ReturnType<typeof amenityCounts>>();
    for (const plan of group.plans) {
      byPlan.set(plan.id, amenityCounts(floorPlanAmenities(catalog, extractions, overrides, plan.id)));
    }
    return byPlan;
  }, [group.plans, catalog, extractions, overrides]);

  const pinnedId = draftPins[group.key] ?? null;
  const label = unitGroupLabel(group.beds, group.baths);
  const displayed = pinnedId
    ? (group.plans.find((plan) => plan.id === pinnedId)?.plan_name ?? null)
    : group.displayPlan.plan_name;

  const togglePin = (planId: string) => setDraftPin(group.key, pinnedId === planId ? null : planId);

  return (
    <Stack gap="sm">
      <Group gap="xs" justify="space-between" align="baseline" wrap="wrap">
        <Text size="sm" c="dimmed">
          {pinnedId ? (
            <>
              Pinned:{" "}
              <Text span fw={600} c="var(--mantine-color-text)">
                {displayed}
              </Text>
            </>
          ) : group.filterSelectedPlanId ? (
            <>
              Filter-selected Floor Plan:{" "}
              <Text span fw={600} c="var(--mantine-color-text)">
                {displayed}
              </Text>
            </>
          ) : (
            <>
              No pin — showing preferred plan:{" "}
              <Text span fw={600} c="var(--mantine-color-text)">
                {displayed}
              </Text>
            </>
          )}
        </Text>
        <Group gap="sm" className={listClasses.legend} aria-hidden>
          {LEGEND.map((item) => (
            <Text key={item.state} component="span" fz="xs" c="dimmed">
              <Text component="span" fw={700} data-state={item.state} className={listClasses.glyph}>
                {item.glyph}
              </Text>{" "}
              {item.word}
            </Text>
          ))}
        </Group>
      </Group>

      <Stack gap="xs">
        {group.plans.map((plan) => {
          const score = scoreByPlan.get(plan.id);
          return (
            <FloorPlanCard
              key={plan.id}
              plan={plan}
              score={score}
              counts={
                countsByPlan.get(plan.id) ?? {
                  confirmed: 0,
                  advertised: 0,
                  absent: 0,
                  unknown: 0,
                }
              }
              diagramUrl={diagramsByPlan.get(plan.id)?.[0] ?? null}
              pinned={pinnedId === plan.id}
              active={openPlanId === plan.id}
              inactive={plan.is_current === false}
              allIn={score?.all_in_components?.total ?? null}
              unitGroupLabel={label}
              disabled={saving}
              onOpen={() => onOpenPlan(plan.id)}
              onTogglePin={() => togglePin(plan.id)}
            />
          );
        })}
      </Stack>
    </Stack>
  );
}
