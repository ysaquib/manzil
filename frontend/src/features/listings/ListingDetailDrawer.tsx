// Detail panel (P1-11, §13.2): right Drawer on desktop and mobile.
// Edits (pins, overrides, fees) batch in draft state until Save.
//
// Drawer.Root stays mounted for the Overview page lifetime. Mantine's Transition
// only animates on opened updates (useDidUpdate), so creating the Drawer on
// first open with opened=true skips the enter slide. Close interception uses a
// ref only — never child→parent setState (that caused a render loop).
import {
  Badge,
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
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { useCallback, useEffect, useRef, useState } from "react";

import { Section } from "../../components/Section";
import { CommentsSection } from "../collaboration/CommentsSection";
import { RatingControl } from "../collaboration/RatingControl";
import { useCurrentMember, useMembers } from "../collaboration/api";
import { useHunt } from "../hunts/api";
import { useCatalog } from "../rubric/api";
import { AllInBreakdown, AllInOverrideControl } from "./AllInCost";
import { activeOverrides } from "./overrides";
import { CriterionBreakdown } from "./CriterionBreakdown";
import { FeeChecklist } from "./FeeChecklist";
import { FloorPlanPins } from "./FloorPlanPins";
import { ListingDetailDraftProvider, useListingDetailDraft } from "./ListingDetailDraft";
import { extractedFeeOriginals, parseOneTimeFees } from "./oneTimeFees";
import { ScoreCell } from "./ScoreCell";
import { SourcesList } from "./SourcesList";
import { useExtractions, useFees, useListings, useOverrides, usePropertyImages } from "./api";
import { PropertyImageCarousel } from "./PropertyImageCarousel";
import { resolveRow, resolveRowWithDraft } from "./unitGroups";
import type { Extraction, Listing } from "./types";
import { memberColor } from "../collaboration/memberColors";

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

// §9.5 utilities-included: the latest `utilities_included` extraction (hunt_id
// NULL) rides in on the same useExtractions map the breakdown already reads.
function UtilitiesIncludedLine({ extraction }: { extraction: Extraction | undefined }) {
  if (!extraction) return null;
  const included = Array.isArray(extraction.value) ? (extraction.value as string[]) : [];
  return (
    <Text size="sm" c="dimmed">
      Utilities included: {included.length > 0 ? included.join(", ") : "none stated"}
    </Text>
  );
}

export function ListingDetailDrawer({
  huntId,
  selection,
  opened,
  onClose,
  onExited,
}: {
  huntId: string;
  selection: DrawerSelection | null;
  opened: boolean;
  onClose: () => void;
  onExited?: () => void;
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
}: {
  huntId: string;
  selection: DrawerSelection;
  opened: boolean;
  isMobile: boolean;
  onClose: () => void;
  setCloseHandler: (fn: () => void) => void;
}) {
  const { data: listings, isLoading: listingsLoading } = useListings(huntId);
  const { listing } = resolveRow(listings ?? [], selection.listingId, selection.groupKey);
  const { data: fees } = useFees(listing?.id ?? "");

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
    >
      <DrawerShell
        huntId={huntId}
        selection={selection}
        listings={listings ?? []}
        isMobile={isMobile}
        onClose={onClose}
        setCloseHandler={setCloseHandler}
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
}: {
  huntId: string;
  selection: DrawerSelection;
  listings: Listing[];
  isMobile: boolean;
  onClose: () => void;
  setCloseHandler: (fn: () => void) => void;
}) {
  const { draftPins, isDirty, saving, saveAll, resetDraft } = useListingDetailDraft();
  const [confirmCloseOpen, setConfirmCloseOpen] = useState(false);

  const { listing, group } = resolveRowWithDraft(
    listings,
    selection.listingId,
    selection.groupKey,
    draftPins,
  );

  const { data: catalog } = useCatalog();
  const { data: extractions, isLoading: extractionsLoading } = useExtractions(
    listing?.property_id ?? "",
    huntId,
  );
  const { data: overrides } = useOverrides(listing?.id ?? "");
  const { data: fees } = useFees(listing?.id ?? "");
  const { data: images, isLoading: imagesLoading } = usePropertyImages(
    listing?.property_id ?? "",
  );
  const { data: members = [] } = useMembers(huntId);
  const { data: currentMember } = useCurrentMember(huntId);
  const membercolor = memberColor(currentMember?.color ?? "");
  const { data: hunt } = useHunt(huntId);
  // Household settings drive the per-person / per-pet move-in estimate (§9.5).
  const household = {
    occupants: Number(hunt?.settings.occupants ?? 1),
    cats: Number(hunt?.settings.cats ?? 0),
    dogs: Number(hunt?.settings.dogs ?? 0),
  };
  const memberNames = new Map(
    members.map((m) => [m.user_id, m.display_name ?? m.user_id] as const),
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

  if (!listing) return null;

  const score = group?.displayScore ?? null;
  const unitLabel = group
    ? `${group.beds === 0 ? "Studio" : `${group.beds} bd`} / ${group.baths} ba`
    : null;
  const isUnavailable = group === null && listing.unavailable_at !== null;

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

  const titleContent = isMobile ? (
    <Stack gap={4}>
      <Title order={4}>{listing.property.name}</Title>
      <Group gap="sm">
        {unitLabel && (
          <Badge variant="outline" color={"surface"}>
            {unitLabel}
          </Badge>
        )}
        {score && group && (
          <ScoreCell total={score.total} pinned={group.pinnedPlanId !== null} />
        )}
      </Group>
    </Stack>
  ) : (
    <Group gap="sm" wrap="nowrap">
      <Title order={4}>{listing.property.name}</Title>
      {unitLabel && (
        <Badge variant="outline" color={"surface"}>
          {unitLabel}
        </Badge>
      )}
      {score && group && (
        <ScoreCell total={score.total} pinned={group.pinnedPlanId !== null} />
      )}
    </Group>
  );

  return (
    <>
      <Drawer.Header>
        <Drawer.Title>{titleContent}</Drawer.Title>
        <Drawer.CloseButton />
      </Drawer.Header>

      <Drawer.Body>
        <Box component="div" style={{ flex: 1, overflow: "auto", minHeight: 0 }} px="md" pt="md">
          <Stack gap="xl" pb="xl">
            <Text size="sm" c="dimmed">
              {listing.property.canonical_address}
            </Text>

            <PropertyImageCarousel images={images ?? []} loading={imagesLoading} />

            <Section title="Score breakdown">
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
                    catalog={catalog ?? []}
                    extractions={extractions ?? new Map()}
                    overrides={overrides ?? []}
                    isMobile={isMobile}
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
            </Section>

            <Section title={`Floor plans (${group?.plans.length ?? 0})`}>
              {group ? (
                <FloorPlanPins group={group} scores={listing.scores} />
              ) : (
                <Text size="sm" c="dimmed">
                  {isUnavailable
                    ? "No available floor plans found."
                    : "No floor plans yet — ingestion may still be running."}
                </Text>
              )}
            </Section>

            <Section title="All-in cost">
              <Stack gap="xs">
                <AllInBreakdown
                  composition={
                    group?.displayScore?.all_in_components ?? listing.all_in_components
                  }
                />
                <AllInOverrideControl
                  overridden={activeOverrides(overrides ?? []).has("all_in_monthly")}
                />
              </Stack>
            </Section>

            <Section title="Fees checklist">
              <Stack gap="sm">
                <FeeChecklist
                  fees={fees ?? []}
                  oneTimeFees={parseOneTimeFees(extractions?.get("one_time_fees")?.value)}
                  household={household}
                  memberNames={memberNames}
                  feeOriginals={extractedFeeOriginals(
                    extractions?.get("mandatory_fees")?.value,
                    extractions?.get("one_time_fees")?.value,
                  )}
                />
                <UtilitiesIncludedLine extraction={extractions?.get("utilities_included")} />
              </Stack>
            </Section>

            <Section title="Ratings">
              {group ? (
                <RatingControl
                  listingId={listing.id}
                  unitGroupKey={group.key}
                  color={membercolor}
                />
              ) : (
                <Text size="sm" c="dimmed">Ratings become available with a Unit Group.</Text>
              )}
            </Section>

            <Section title="Comments">
              <CommentsSection
                listingId={listing.id}
                members={members}
                currentUnitGroup={group ? { key: group.key, label: unitLabel ?? group.key } : null}
              />
            </Section>

            <Section title="Sources">
              <SourcesList sources={listing.property.sources} sourcePolicy={listing.source_policy} />
            </Section>
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
