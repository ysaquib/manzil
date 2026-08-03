// Detail panel (P1-11, §13.2): right Drawer on desktop and mobile.
// Edits (pins, overrides, fees) batch in draft state until Save.
//
// Drawer.Root stays mounted for the Overview page lifetime. Mantine's Transition
// only animates on opened updates (useDidUpdate), so creating the Drawer on
// first open with opened=true skips the enter slide. Close interception uses a
// ref only — never child→parent setState (that caused a render loop).
import {
  ActionIcon,
  Box,
  Button,
  Center,
  Drawer,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconMapPin, IconMessageCircle } from "@tabler/icons-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { SectionCard } from "../../components/SectionCard";
import { ProblematicBadge } from "../../components/badges/ListingBadges";
import { CommentsSection } from "../collaboration/CommentsSection";
import { RatingControl } from "../collaboration/RatingControl";
import { useCurrentMember, useMembers } from "../collaboration/api";
import { useListingFeeProposals } from "../visits/api";
import { ListingVisits } from "../visits/ListingVisits";
import { memberDisplayNameMap } from "../collaboration/memberDisplay";
import { useHunt } from "../hunts/api";
import { useFeedbackOptional } from "../feedback/FeedbackContext";
import { AutoResolvedCheckpointReview } from "../jobs/AutoResolvedCheckpointReview";
import type { Job } from "../jobs/api";
import { ListingLocationMap } from "../map/ListingLocationMap";
import { useResolvedCatalog } from "../rubric/api";
import { activeOverrides, extractionForFloorPlan } from "./overrides";
import { CriterionBreakdown } from "./CriterionBreakdown";
import { DrawerHero } from "./DrawerHero";
import { CostAndFees } from "./CostAndFees";
import { FloorPlanDetailModal } from "./FloorPlanDetailModal";
import { FloorPlanList } from "./FloorPlanList";
import { UnmatchedDiagrams, unmatchedDiagrams } from "./UnmatchedDiagrams";
import { ListingDetailDraftProvider, useListingDetailDraft } from "./ListingDetailDraft";
import { propertyLocationLabel } from "./locality";
import { PropertyContactRow } from "./PropertyContact";
import { extractedFeeOriginals, parseOneTimeFees } from "./oneTimeFees";
import { SourcesList } from "./SourcesList";
import {
  useExtractions, useFees, useListings, useOverrides, usePropertyImages, useUtilityOverrides,
} from "./api";
import { resolveRow, resolveRowWithDraft, unitGroupLabel } from "./unitGroups";
import {
  DEFAULT_OVERVIEW_FILTERS,
  selectFilterDisplayPlan,
  type OverviewFilterState,
} from "./overviewRows";
import type { Listing } from "./types";
import drawerClasses from "./ListingDetailDrawer.module.css";

export interface DrawerSelection {
  listingId: string;
  groupKey: string | null;
}

const drawerStyles = {
  content: {
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    height: "calc(100dvh - var(--drawer-offset, 0px) * 2)",
    maxHeight: "calc(100dvh - var(--drawer-offset, 0px) * 2)",
    // Anchor for the drawer-scoped Floor Plan detail modal (P3-SC5): its
    // absolute root/inner/overlay resolve against the whole drawer column
    // (header + body), not the scroll region, and stay outside overflow:auto.
    position: "relative",
  },
  body: {
    display: "flex",
    flexDirection: "column",
    flex: 1,
    overflow: "hidden",
    minHeight: 0,
    padding: 0,
  },
} as const;

export function ListingDetailDrawer({
  huntId,
  selection,
  opened,
  onClose,
  onExited,
  filters = DEFAULT_OVERVIEW_FILTERS,
  jobs = [],
  answeringCheckpoint = false,
  onAnswerCheckpoint,
  isGhost = false,
}: {
  huntId: string;
  selection: DrawerSelection | null;
  opened: boolean;
  onClose: () => void;
  onExited?: () => void;
  filters?: OverviewFilterState;
  jobs?: Job[];
  answeringCheckpoint?: boolean;
  onAnswerCheckpoint?: (jobId: string, choice: string, text?: string) => void;
  isGhost?: boolean;
}) {
  const isMobile = useMediaQuery("(max-width: 48em)");
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const closeHandlerRef = useRef<() => void>(() => onCloseRef.current());
  const setCloseHandler = useCallback((fn: () => void) => {
    closeHandlerRef.current = fn;
  }, []);

  return (
    <Drawer.Root
      opened={opened}
      onClose={() => closeHandlerRef.current()}
      position="right"
      size={isMobile ? "100%" : "lg"}
      transitionProps={{ duration: 220, timingFunction: "ease", onExited }}
      styles={drawerStyles}
    >
      <Drawer.Overlay />
      <Drawer.Content>
        {selection ? (
          <SelectionGate
            huntId={huntId}
            selection={selection}
            opened={opened}
            isMobile={!!isMobile}
            onClose={onClose}
            setCloseHandler={setCloseHandler}
            filters={filters}
            jobs={jobs}
            answeringCheckpoint={answeringCheckpoint}
            onAnswerCheckpoint={onAnswerCheckpoint}
            isGhost={isGhost}
          />
        ) : null}
      </Drawer.Content>
    </Drawer.Root>
  );
}

function SelectionGate({
  huntId,
  selection,
  opened,
  isMobile,
  onClose,
  setCloseHandler,
  filters,
  jobs,
  answeringCheckpoint,
  onAnswerCheckpoint,
  isGhost,
}: {
  huntId: string;
  selection: DrawerSelection;
  opened: boolean;
  isMobile: boolean;
  onClose: () => void;
  setCloseHandler: (fn: () => void) => void;
  filters: OverviewFilterState;
  jobs: Job[];
  answeringCheckpoint: boolean;
  onAnswerCheckpoint?: (jobId: string, choice: string, text?: string) => void;
  isGhost: boolean;
}) {
  const { data: listings, isLoading: listingsLoading } = useListings(huntId);
  const { listing } = resolveRow(listings ?? [], selection.listingId, selection.groupKey);
  const { data: fees } = useFees(listing?.id ?? "");
  const { data: utilityOverrides } = useUtilityOverrides(listing?.id ?? "");

  useEffect(() => {
    if (opened && !listingsLoading && listings && !listing) onClose();
  }, [opened, listingsLoading, listings, listing, onClose]);

  useEffect(() => {
    return () => setCloseHandler(() => onClose());
  }, [onClose, setCloseHandler]);

  if (!listing) return null;

  return (
    <ListingDetailDraftProvider
      key={listing.id}
      huntId={huntId}
      listing={listing}
      serverFees={fees ?? []}
      serverUtilityOverrides={utilityOverrides ?? []}
    >
      <DrawerShell
        huntId={huntId}
        selection={selection}
        listings={listings ?? []}
        isMobile={isMobile}
        onClose={onClose}
        setCloseHandler={setCloseHandler}
        filters={filters}
        jobs={jobs}
        answeringCheckpoint={answeringCheckpoint}
        onAnswerCheckpoint={onAnswerCheckpoint}
        isGhost={isGhost}
      />
    </ListingDetailDraftProvider>
  );
}

function DrawerShell({
  huntId,
  selection,
  listings,
  isMobile,
  onClose,
  setCloseHandler,
  filters,
  jobs,
  answeringCheckpoint,
  onAnswerCheckpoint,
  isGhost,
}: {
  huntId: string;
  selection: DrawerSelection;
  listings: Listing[];
  isMobile: boolean;
  onClose: () => void;
  setCloseHandler: (fn: () => void) => void;
  filters: OverviewFilterState;
  jobs: Job[];
  answeringCheckpoint: boolean;
  onAnswerCheckpoint?: (jobId: string, choice: string, text?: string) => void;
  isGhost: boolean;
}) {
  const { draftPins, setDraftPin, isDirty, saving, saveAll, resetDraft } = useListingDetailDraft();
  const [confirmCloseOpen, setConfirmCloseOpen] = useState(false);
  const [openFloorPlanId, setOpenFloorPlanId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [headerScrolled, setHeaderScrolled] = useState(false);

  const syncHeaderScroll = useCallback(() => {
    const el = scrollRef.current;
    setHeaderScrolled((el?.scrollTop ?? 0) > 0);
  }, []);

  const { listing, group: resolvedGroup } = resolveRowWithDraft(
    listings,
    selection.listingId,
    selection.groupKey,
    draftPins,
  );
  const group =
    listing && resolvedGroup
      ? selectFilterDisplayPlan(
          { listing, group: resolvedGroup, state: null },
          filters,
        ).group
      : resolvedGroup;

  const { data: catalog = [] } = useResolvedCatalog(huntId);
  const { data: extractions, isLoading: extractionsLoading } = useExtractions(
    listing?.property_id ?? "",
    huntId,
  );
  const { data: overrides } = useOverrides(listing?.id ?? "");
  const { data: fees } = useFees(listing?.id ?? "");
  const { data: utilityOverrides } = useUtilityOverrides(listing?.id ?? "");
  const { data: images, isLoading: imagesLoading } = usePropertyImages(
    listing?.property_id ?? "",
  );
  const { data: members = [] } = useMembers(huntId);
  const { data: currentMember } = useCurrentMember(huntId);
  // Figures confirmed on a tour and offered to this Listing (VC-7).
  const { data: feeProposals } = useListingFeeProposals(listing?.id);
  const { data: hunt } = useHunt(huntId);
  const openFeedback = useFeedbackOptional();
  // Household settings drive the per-person / per-pet move-in estimate (§9.5).
  const household = {
    occupants: Number(hunt?.settings.occupants ?? 1),
    cats: Number(hunt?.settings.cats ?? 0),
    dogs: Number(hunt?.settings.dogs ?? 0),
  };
  const memberNames = memberDisplayNameMap(members);
  const autoResolvedJob = jobs.find(
    (job) =>
      job.hunt_listing_id === listing?.id &&
      job.auto_resolved_checkpoint &&
      !job.auto_resolved_checkpoint.corrected_at,
  );

  useEffect(() => {
    setCloseHandler(() => {
      if (!isDirty) {
        onClose();
        return;
      }
      setConfirmCloseOpen(true);
    });
  }, [isDirty, onClose, setCloseHandler]);

  useEffect(() => {
    setHeaderScrolled(false);
    setOpenFloorPlanId(null);
    scrollRef.current?.scrollTo({ top: 0 });
  }, [listing?.id, selection?.groupKey]);

  if (!listing) return null;

  const score = group?.displayScore ?? null;
  const displayFloorPlanId = group?.displayPlan.id ?? null;
  const unitLabel = group
    ? `${group.beds === 0 ? "Studio" : `${group.beds} bd`} / ${group.baths} ba`
    : null;
  const isUnavailable = group === null && listing.unavailable_at !== null;
  // Display metadata for the hero's all-in stat: the pinned/displayed plan's
  // composition, falling back to the listing-level projection (§9.5 P3-9).
  const composition = group?.displayScore?.all_in_components ?? listing.all_in_components;
  // P3-SC8: the same display-plan rule as the all-in composition — the move-in
  // ledger must describe the plan the drawer is showing.
  const moveInComposition =
    group?.displayScore?.move_in_components ?? listing.move_in_components ?? null;
  const utilitiesValue = extractionForFloorPlan(
    extractions ?? [],
    "utilities_included",
    null,
  )?.value;
  const extractedIncluded = Array.isArray(utilitiesValue)
    ? utilitiesValue.filter((item): item is string => typeof item === "string")
    : null;

  const handleDiscard = () => {
    resetDraft();
    setConfirmCloseOpen(false);
    onClose();
  };

  const handleSaveAndClose = async () => {
    const ok = await saveAll();
    setConfirmCloseOpen(false);
    if (ok) onClose();
  };

  const openFloorPlan = group?.plans.find((plan) => plan.id === openFloorPlanId) ?? null;
  const openFloorPlanScore = openFloorPlan
    ? (listing.scores.find((row) => row.floor_plan_id === openFloorPlan.id) ?? undefined)
    : undefined;
  const openFloorPlanDiagramUrls = useMemo(() => {
    if (!openFloorPlan) return [];
    const urls: string[] = [];
    for (const image of images ?? []) {
      if (image.kind !== "floor_plan_diagram") continue;
      if (image.floorPlanAssociations?.includes(openFloorPlan.id)) urls.push(image.url);
    }
    return urls;
  }, [images, openFloorPlan]);

  return (
    <>
      <Drawer.Header
        className={drawerClasses.drawerHeader}
        data-scrolled={headerScrolled || undefined}
        style={{ alignItems: "flex-start" }}
      >
        <Stack gap={0}>
          <Text className={drawerClasses.eyebrow} tt="uppercase" fw={600} c="dimmed">
            Listing
          </Text>
          <Group gap="xs">
            <Title order={3} className={drawerClasses.title}>
              {listing.property.name}
            </Title>
            {(extractions ?? []).some(
              (extraction) =>
                extraction.disputed &&
                extraction.resolution_rule === "conservative_disputed",
            ) && <ProblematicBadge />}
          </Group>
          <Group gap={7} wrap="nowrap" className={drawerClasses.addr}>
            <IconMapPin size={13} stroke={2} />
            <Text size="sm" component="span" c="dimmed">
              {listing.property.canonical_address}
            </Text>
          </Group>
        </Stack>
        <Group gap={4} ml="auto" wrap="nowrap">
          {openFeedback && (
            <Tooltip label="Submit feedback">
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label="Submit feedback"
                onClick={openFeedback}
              >
                <IconMessageCircle size={18} stroke={1.5} />
              </ActionIcon>
            </Tooltip>
          )}
          <Drawer.CloseButton />
        </Group>
      </Drawer.Header>

      <Drawer.Body>
        <Box
          ref={scrollRef}
          component="div"
          onScroll={syncHeaderScroll}
          className={drawerClasses.drawerScroll}
          px="md"
          pt="xs"
        >
          <DrawerHero
            // Property photos only. Floor Plan diagrams belong to their plan's
            // detail surface and must never stand in for a Property photo
            // (workbook §7.1).
            images={(images ?? []).filter((image) => image.kind !== "floor_plan_diagram")}
            imagesLoading={imagesLoading}
            score={group?.displayScore?.total ?? null}
            allIn={composition?.total ?? null}
            estimated={composition?.estimated_total ?? null}
            bedsBaths={unitLabel}
          />

          <Stack gap="md" pt="md" pb="xl">
            {autoResolvedJob?.auto_resolved_checkpoint && (
              <SectionCard title="Review auto-resolved checkpoint">
                <AutoResolvedCheckpointReview
                  checkpoint={autoResolvedJob.auto_resolved_checkpoint}
                  canAnswer={
                    isGhost === true ||
                    currentMember?.role === "owner" ||
                    currentMember?.role === "curator" ||
                    currentMember?.user_id === listing.added_by
                  }
                  answering={answeringCheckpoint}
                  onAnswer={(choice, text) =>
                    onAnswerCheckpoint?.(autoResolvedJob.id, choice, text)
                  }
                />
              </SectionCard>
            )}

            <SectionCard
              title="Why this score"
              hint={score ? `${score.breakdown.criteria.length} criteria` : undefined}
            >
              {score ? (
                extractionsLoading ? (
                  <Center py="md">
                    <Loader size="sm" />
                  </Center>
                ) : (
                  <CriterionBreakdown
                    huntId={huntId}
                    listingId={listing.id}
                    breakdown={score.breakdown}
                    catalog={catalog}
                    extractions={extractions ?? []}
                    overrides={overrides ?? []}
                    floorPlanId={displayFloorPlanId}
                    isMobile={isMobile}
                    members={members}
                  />
                )
              ) : isUnavailable ? (
                <Text size="sm" c="dimmed">
                  No available floor plans found for this property.
                </Text>
              ) : (
                <Text size="sm" c="dimmed">
                  Not scored yet — ingestion may still be running (see Tasks).
                </Text>
              )}
            </SectionCard>

            <SectionCard title="Cost &amp; fees">
              <CostAndFees
                composition={composition}
                moveIn={moveInComposition}
                fees={fees ?? []}
                oneTimeFees={parseOneTimeFees(
                  extractionForFloorPlan(extractions ?? [], "one_time_fees", null)?.value,
                )}
                household={household}
                memberNames={memberNames}
                feeOriginals={extractedFeeOriginals(
                  extractionForFloorPlan(extractions ?? [], "mandatory_fees", null)?.value,
                  extractionForFloorPlan(extractions ?? [], "one_time_fees", null)?.value,
                )}
                extractedIncluded={extractedIncluded}
                utilityOverrides={utilityOverrides ?? []}
                allInOverridden={activeOverrides(overrides ?? [], displayFloorPlanId).has(
                  "all_in_monthly",
                )}
                securityDepositOverridden={activeOverrides(
                  overrides ?? [],
                  displayFloorPlanId,
                ).has("security_deposit")}
                floorPlanId={displayFloorPlanId}
                huntId={huntId}
                proposals={feeProposals ?? []}
                // Deciding is a cost write, so it follows the Override
                // permission (§4.2) — the same rule the API and RLS enforce.
                canDecideProposals={
                  currentMember?.role === "owner" ||
                  currentMember?.role === "curator" ||
                  currentMember?.user_id === listing.added_by
                }
              />
            </SectionCard>

            <SectionCard title="Floor plans" hint={`${group?.plans.length ?? 0} plans`}>
              {group ? (
                <FloorPlanList
                  group={group}
                  scores={listing.scores}
                  catalog={catalog}
                  extractions={extractions ?? []}
                  overrides={overrides ?? []}
                  images={images ?? []}
                  openPlanId={openFloorPlanId}
                  onOpenPlan={setOpenFloorPlanId}
                />
              ) : (
                <Text size="sm" c="dimmed">
                  {isUnavailable
                    ? "No available floor plans found."
                    : "No floor plans yet — ingestion may still be running."}
                </Text>
              )}
            </SectionCard>

            {unmatchedDiagrams(images ?? []).length > 0 && (
              <SectionCard
                title="Unmatched floor plan diagrams"
                hint={`${unmatchedDiagrams(images ?? []).length}`}
              >
                <UnmatchedDiagrams images={images ?? []} />
              </SectionCard>
            )}

            {/* Visits sit beside the scored record, never inside it (§9.7):
                the whole point of the tour is that it is a different kind of
                evidence. This is also where a described unit that matches no
                advertised Unit Group stays visible. */}
            <SectionCard title="Visits">
              <ListingVisits
                huntId={huntId}
                propertyId={listing.property_id}
                huntListingId={listing.id}
              />
            </SectionCard>

            <SectionCard title="Notes & ratings">
              <Stack gap="md">
                {group ? (
                  <RatingControl
                    listingId={listing.id}
                    unitGroupKey={group.key}
                    huntId={huntId}
                  />
                ) : (
                  <Text size="sm" c="dimmed">
                    Ratings become available with a Unit Group.
                  </Text>
                )}
                <CommentsSection
                  listingId={listing.id}
                  members={members}
                  currentUnitGroup={
                    group ? { key: group.key, label: unitLabel ?? group.key } : null
                  }
                />
              </Stack>
            </SectionCard>

            {/* Near the bottom by design: the map answers "where is this?"
                once the reader has decided the score is worth caring about. */}
            <SectionCard
              title="Location"
              hint={propertyLocationLabel(listing.property)}
            >
              <Stack gap="sm">
                <ListingLocationMap
                  property={listing.property}
                  score={group?.displayScore?.total ?? null}
                />
                <PropertyContactRow propertyId={listing.property.id} />
              </Stack>
            </SectionCard>

            <SectionCard title="Sources">
              <SourcesList
                sources={listing.property.sources}
                sourcePolicy={listing.source_policy}
                huntId={huntId}
                listingId={listing.id}
                singleSourceReason={listing.single_source_reason}
                canEdit={
                  isGhost === true ||
                  currentMember?.role === "owner" ||
                  currentMember?.user_id === listing.added_by
                }
                jobs={jobs}
              />
            </SectionCard>
          </Stack>
        </Box>

        {isDirty && (
          <Box
            py="sm"
            px="md"
            bg="var(--mantine-color-body)"
            style={{
              flexShrink: 0,
              borderTop: "1px solid var(--mantine-color-default-border)",
            }}
          >
            <Group justify="space-between" align="center" wrap="wrap" gap="sm">
              <Text size="sm" c="dimmed">
                Unsaved changes
              </Text>
              <Button size="xs" onClick={() => void saveAll()} loading={saving}>
                Save
              </Button>
            </Group>
          </Box>
        )}
      </Drawer.Body>

      {group && (
        <FloorPlanDetailModal
          opened={openFloorPlan !== null}
          plan={openFloorPlan}
          score={openFloorPlanScore}
          huntId={huntId}
          listingId={listing.id}
          unitGroupLabel={unitGroupLabel(group.beds, group.baths)}
          planCount={group.plans.length}
          catalog={catalog}
          extractions={extractions ?? []}
          overrides={overrides ?? []}
          sources={listing.property.sources}
          diagramUrls={openFloorPlanDiagramUrls}
          pinned={openFloorPlan ? (draftPins[group.key] ?? null) === openFloorPlan.id : false}
          saving={saving}
          isMobile={isMobile}
          members={members}
          onClose={() => setOpenFloorPlanId(null)}
          onTogglePin={() =>
            openFloorPlan &&
            setDraftPin(
              group.key,
              (draftPins[group.key] ?? null) === openFloorPlan.id ? null : openFloorPlan.id,
            )
          }
        />
      )}

      <Modal
        opened={confirmCloseOpen}
        onClose={() => setConfirmCloseOpen(false)}
        title="Discard unsaved changes?"
        zIndex={300}
      >
        <Stack gap="md">
          <Text size="sm">
            You have edits that haven&apos;t been saved yet. Keep editing, discard them, or save
            before closing.
          </Text>
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setConfirmCloseOpen(false)}>
              Keep editing
            </Button>
            <Button variant="default" color="red" onClick={handleDiscard}>
              Discard
            </Button>
            <Button onClick={() => void handleSaveAndClose()} loading={saving}>
              Save changes
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
