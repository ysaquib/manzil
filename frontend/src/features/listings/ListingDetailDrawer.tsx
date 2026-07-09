// Detail panel (P1-11, §13.2): side Drawer on desktop, bottom sheet on mobile.
// Sections: score breakdown (persisted §9.3 contract, rendered directly),
// floor plans + pin, fees checklist, sources. Comments, ratings, image
// gallery, score history, and Investigate are Phase 2/3 — deliberately absent.
import { Badge, Center, Drawer, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";

import { Section } from "../../components/Section";
import { semantic } from "../../theme";
import { useCatalog } from "../rubric/api";
import { CriterionBreakdown } from "./CriterionBreakdown";
import { FeeChecklist } from "./FeeChecklist";
import { FloorPlanPins } from "./FloorPlanPins";
import { ScoreCell } from "./ScoreCell";
import { SourcesList } from "./SourcesList";
import { useExtractions, useFees, useOverrides } from "./api";
import type { OverviewRow } from "./overviewRows";

export function ListingDetailDrawer({
  huntId,
  row,
  opened,
  onClose,
}: {
  huntId: string;
  row: OverviewRow;
  opened: boolean;
  onClose: () => void;
}) {
  const isMobile = useMediaQuery("(max-width: 48em)");
  const { listing, group } = row;

  const { data: catalog } = useCatalog();
  const { data: extractions, isLoading: extractionsLoading } = useExtractions(
    listing.property_id,
    huntId,
  );
  const { data: overrides } = useOverrides(listing.id);
  const { data: fees } = useFees(listing.id);

  const score = group.displayScore;
  const unitLabel = `${group.beds === 0 ? "Studio" : `${group.beds} bd`} / ${group.baths} ba`;

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position={isMobile ? "bottom" : "right"}
      size={isMobile ? "85%" : "lg"}
      title={
        isMobile ? (
          <Stack gap={4}>
            <Title order={4}>{listing.property.name}</Title>
            <Group gap="sm">
              <Badge variant="outline" color={semantic.surface}>
                {unitLabel}
              </Badge>
              {score && <ScoreCell total={score.total} pinned={group.pinnedPlanId !== null} />}
            </Group>
          </Stack>
        ) : (
          <Group gap="sm" wrap="nowrap">
            <Title order={4}>{listing.property.name}</Title>
            <Badge variant="outline" color={semantic.surface}>
              {unitLabel}
            </Badge>
            {score && <ScoreCell total={score.total} pinned={group.pinnedPlanId !== null} />}
          </Group>
        )
      }
    >
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
              />
            )
          ) : (
            <Text size="sm" c="dimmed">
              Not scored yet — ingestion may still be running (see Tasks).
            </Text>
          )}
        </Section>

        <Section title={`Floor plans (${group.plans.length})`}>
          <FloorPlanPins huntId={huntId} listing={listing} group={group} />
        </Section>

        <Section title="Fees checklist">
          <FeeChecklist huntId={huntId} listingId={listing.id} fees={fees ?? []} />
        </Section>

        <Section title="Sources">
          <SourcesList sources={listing.property.sources} sourcePolicy={listing.source_policy} />
        </Section>
      </Stack>
    </Drawer>
  );
}
