// Detail panel (P1-11, §13.2): side Drawer on desktop, bottom sheet on mobile.
// Edits (pins, overrides, fees) batch in draft state until Save.
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
import { useEffect, useState } from "react";

import { Section } from "../../components/Section";
import { semantic } from "../../theme";
import { useCatalog } from "../rubric/api";
import { CriterionBreakdown } from "./CriterionBreakdown";
import { FeeChecklist } from "./FeeChecklist";
import { FloorPlanPins } from "./FloorPlanPins";
import { ListingDetailDraftProvider, useListingDetailDraft } from "./ListingDetailDraft";
import { ScoreCell } from "./ScoreCell";
import { SourcesList } from "./SourcesList";
import { useExtractions, useFees, useListings, useOverrides } from "./api";
import { resolveRow, resolveRowWithDraft } from "./unitGroups";
import type { Extraction, Listing } from "./types";

export interface DrawerSelection {
  listingId: string;
  groupKey: string | null;
}

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
}: {
  huntId: string;
  selection: DrawerSelection;
  opened: boolean;
  onClose: () => void;
}) {
  const { data: listings, isLoading: listingsLoading } = useListings(huntId);
  const { listing } = resolveRow(
    listings ?? [],
    selection.listingId,
    selection.groupKey,
  );
  const { data: fees } = useFees(listing?.id ?? "");

  useEffect(() => {
    if (opened && !listingsLoading && listings && !listing) onClose();
  }, [opened, listingsLoading, listings, listing, onClose]);

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
        opened={opened}
        onClose={onClose}
      />
    </ListingDetailDraftProvider>
  );
}

function DrawerShell({
  huntId,
  selection,
  listings,
  opened,
  onClose,
}: {
  huntId: string;
  selection: DrawerSelection;
  listings: Listing[];
  opened: boolean;
  onClose: () => void;
}) {
  const isMobile = useMediaQuery("(max-width: 48em)");
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

  if (!listing) return null;

  const score = group?.displayScore ?? null;
  const unitLabel = group
    ? `${group.beds === 0 ? "Studio" : `${group.beds} bd`} / ${group.baths} ba`
    : null;
  const isUnavailable = group === null && listing.unavailable_at !== null;

  const requestClose = () => {
    if (!isDirty) {
      onClose();
      return;
    }
    setConfirmCloseOpen(true);
  };

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
          <Badge variant="outline" color={semantic.surface}>
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
        <Badge variant="outline" color={semantic.surface}>
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
      <Drawer
        opened={opened}
        onClose={requestClose}
        position={isMobile ? "bottom" : "right"}
        size={isMobile ? "85%" : "lg"}
        title={titleContent}
        styles={{
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
        }}
      >
        <Box component="div" style={{ flex: 1, overflow: "auto", minHeight: 0 }} px="md" pt="md">
          <Stack gap="xl" pb="xl">
            <Text size="sm" c="dimmed">
              {listing.property.canonical_address}
            </Text>

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
                    isMobile={!!isMobile}
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

            <Section title="Fees checklist">
              <Stack gap="sm">
                <FeeChecklist fees={fees ?? []} />
                <UtilitiesIncludedLine extraction={extractions?.get("utilities_included")} />
              </Stack>
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
      </Drawer>

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
