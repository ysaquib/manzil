// Floor Plan detail surface (P3-SC5 item 7, DESIGN §9.4 / workbook §7.1).
//
// A nested modal above the Listing Drawer — scoped to the drawer's column on
// desktop so the Overview behind stays lit, full-screen below `sm`. The
// Listing draft stays mounted throughout: pinning here writes the same draft
// the card list writes, and closing the modal leaves the drawer dirty.
//
// Everything shown is this plan's own: its facts, its scoped amenities with
// evidence, its diagram, and its score breakdown — never the Unit Group's
// displayed plan (§9.4).
import {
  Alert,
  Anchor,
  Badge,
  Box,
  Button,
  Collapse,
  Divider,
  Group,
  Image,
  Modal,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { IconChevronLeft, IconExternalLink, IconInfoCircle, IconPinFilled } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import type { CatalogEntry } from "../rubric/api";
import { CriterionBreakdown } from "./CriterionBreakdown";
import { displayValue } from "./displayValue";
import {
  AMENITY_STATES,
  type AmenityFact,
  type AmenityState,
  floorPlanAmenities,
  groupAmenities,
} from "./floorPlanAmenities";
import classes from "./FloorPlanDetailModal.module.css";
import { formatRange } from "./overviewRows";
import { formatScore, scoreColor, scoreLabel } from "./scoreBands";
import type { Extraction, FloorPlan, Override, PropertySource, Score } from "./types";
import type { HuntContributor, HuntMember } from "../collaboration/api";

const STATE_HEADING: Record<AmenityState, { title: string; hint: string; glyph: string }> = {
  confirmed: { title: "Confirmed", hint: "stated for this plan", glyph: "✓" },
  advertised: { title: "Advertised, unconfirmed", hint: "not gate-sufficient", glyph: "~" },
  absent: { title: "Not available", hint: "explicitly absent", glyph: "✕" },
  unknown: { title: "Unknown", hint: "no claim found", glyph: "?" },
};

function Fact({ label, value, sub }: { label: string; value: string; sub?: string | null }) {
  return (
    <Box>
      <Text fz="0.625rem" tt="uppercase" fw={700} c="dimmed" lts="0.07em">
        {label}
      </Text>
      <Text size="sm" style={{ fontVariantNumeric: "tabular-nums" }}>
        {value}
      </Text>
      {sub && (
        <Text size="xs" c="dimmed">
          {sub}
        </Text>
      )}
    </Box>
  );
}

function AmenityEvidence({ fact }: { fact: AmenityFact }) {
  const { extraction } = fact;
  return (
    <Alert variant="light" color="dusky" title={`Evidence · ${fact.label}`} p="sm">
      <Stack gap={5}>
        {fact.overridden && (
          <Text size="sm">
            Set by hand. Extracted value:{" "}
            <Text span fw={600}>
              {displayValue(extraction?.value ?? null, fact.key)}
            </Text>
          </Text>
        )}
        {extraction?.evidence_quote ? (
          <Text size="sm" fs="italic">
            “{extraction.evidence_quote}”
          </Text>
        ) : (
          !fact.overridden && <Text size="sm">No supporting text was found for this plan.</Text>
        )}
        <Text size="xs" c="dimmed">
          {fact.scope ? `${fact.scope} · ` : ""}
          {extraction
            ? `${extraction.confidence} confidence · ${extraction.model}`
            : "no claim in any Source"}
          {extraction?.extracted_at
            ? ` · extracted ${new Date(extraction.extracted_at).toLocaleDateString()}`
            : ""}
        </Text>
        {extraction?.resolution_rule && (
          <Text size="xs" c="dimmed">
            Resolution: {extraction.resolution_rule.replaceAll("_", " ")}
          </Text>
        )}
      </Stack>
    </Alert>
  );
}

function AmenityGroup({
  state,
  facts,
  openKey,
  onToggle,
}: {
  state: AmenityState;
  facts: AmenityFact[];
  openKey: string | null;
  onToggle: (key: string) => void;
}) {
  if (facts.length === 0) return null;
  const heading = STATE_HEADING[state];
  return (
    <Stack gap={6}>
      <Group gap="xs" align="baseline">
        <Text fz="xs" fw={700} tt="uppercase" lts="0.05em" className={classes.mark} data-state={state}>
          {heading.title} · {facts.length}
        </Text>
        <Text fz="xs" c="dimmed">
          {heading.hint}
        </Text>
      </Group>
      <Group gap={6}>
        {facts.map((fact) => {
          const selected = openKey === fact.id;
          const typed =
            Array.isArray(fact.value) ||
            (typeof fact.value === "string" &&
              fact.value !== "confirmed" &&
              fact.value !== "none" &&
              fact.value !== "advertised_unconfirmed");
          return (
            <Box
              key={fact.id}
              className={`${classes.chip} ${selected ? classes.chipSelected : ""}`}
              data-state={state}
            >
              <Box component="span" className={classes.chipLabel}>
                <Text component="span" fz="xs" className={classes.mark} data-state={state} aria-hidden>
                  {heading.glyph}
                </Text>
                <Text component="span" size="sm">
                  {fact.label}
                  {typed ? `: ${displayValue(fact.value, fact.key)}` : ""}
                </Text>
                {fact.scope && (
                  <Text component="span" fz="0.625rem" tt="uppercase" fw={700} c="dimmed">
                    {fact.scope}
                  </Text>
                )}
              </Box>
              <UnstyledButton
                className={classes.chipEvidence}
                aria-expanded={selected}
                aria-label={`Evidence for ${fact.label}`}
                onClick={() => onToggle(fact.id)}
              >
                <IconInfoCircle size={14} stroke={2} />
              </UnstyledButton>
            </Box>
          );
        })}
      </Group>
    </Stack>
  );
}

export interface FloorPlanDetailModalProps {
  opened: boolean;
  plan: FloorPlan | null;
  score: Score | undefined;
  huntId: string;
  listingId: string;
  unitGroupLabel: string;
  planCount: number;
  catalog: CatalogEntry[];
  extractions: Extraction[];
  overrides: Override[];
  sources: PropertySource[];
  /** Signed URLs for this plan's current diagrams, in display order. */
  diagramUrls: string[];
  pinned: boolean;
  saving?: boolean;
  isMobile: boolean;
  members?: (HuntMember | HuntContributor)[];
  readOnly?: boolean;
  onClose: () => void;
  onTogglePin: () => void;
}

export function FloorPlanDetailModal({
  opened,
  plan,
  score,
  huntId,
  listingId,
  unitGroupLabel,
  planCount,
  catalog,
  extractions,
  overrides,
  sources,
  diagramUrls,
  pinned,
  saving,
  isMobile,
  members = [],
  readOnly = false,
  onClose,
  onTogglePin,
}: FloorPlanDetailModalProps) {
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);

  // A different plan is a different set of claims; never carry a disclosure
  // from one plan into the next.
  useEffect(() => setOpenEvidence(null), [plan?.id]);

  if (!plan) return null;

  const amenities = floorPlanAmenities(catalog, extractions, overrides, plan.id);
  const groups = groupAmenities(amenities);
  const openFact = amenities.find((fact) => fact.id === openEvidence) ?? null;
  const source = sources.find((row) => row.id === plan.source_id) ?? null;
  const planUrl = plan.detail_url ?? source?.url ?? null;
  const sourceDomain = source?.site_domain ?? "the source";
  const allIn = score?.all_in_components?.total ?? null;

  // Desktop: re-anchor Mantine's viewport-fixed root/inner/overlay onto
  // `Drawer.Content` (which owns `position: relative`), sibling to the scroll
  // region so overflow:auto cannot clip the overlay. The drawer column stays
  // lit against the Overview behind it. Mobile: drop them entirely and let
  // `fullScreen` behave normally — a real fork, exercise both.
  //
  // This is the `styles` API rather than a CSS Module on purpose (UI_DESIGN §3
  // escalation step 3): Mantine's own `Modal-root`/`Modal-inner` rules win the
  // cascade against a module class, and inline styles are the only reliable
  // way to override slot positioning.
  const drawerScopedStyles = isMobile
    ? undefined
    : {
        root: { position: "absolute" as const, inset: 0 },
        inner: {
          position: "absolute" as const,
          inset: 0,
          padding: "var(--mantine-spacing-md) var(--mantine-spacing-sm)",
        },
        overlay: { position: "absolute" as const, inset: 0 },
        content: { maxHeight: "100%" },
      };

  return (
    <Modal.Root
      opened={opened}
      onClose={onClose}
      withinPortal={false}
      fullScreen={isMobile}
      size="lg"
      returnFocus
      styles={drawerScopedStyles}
      aria-label={`${plan.plan_name} floor plan detail`}
    >
      <Modal.Overlay />
      <Modal.Content>
        <Modal.Header style={{ alignItems: "flex-start" }}>
          <Stack gap={2}>
            <Anchor
              component="button"
              type="button"
              size="xs"
              fw={600}
              className={classes.crumb}
              onClick={onClose}
            >
              <Group gap={4} wrap="nowrap">
                <IconChevronLeft size={13} stroke={2.5} />
                {`${unitGroupLabel} · ${planCount} ${planCount === 1 ? "plan" : "plans"}`}
              </Group>
            </Anchor>
            <Group gap="xs">
              <Title order={4}>{plan.plan_name}</Title>
              {score && (
                <Badge variant="light" color={scoreColor(score.total)} aria-label="plan score">
                  {formatScore(score.total)} · {scoreLabel(score.total)}
                </Badge>
              )}
              {pinned && (
                <Badge variant="light" leftSection={<IconPinFilled size={11} />}>
                  Pinned
                </Badge>
              )}
            </Group>
          </Stack>
          <Modal.CloseButton ml="auto" />
        </Modal.Header>

        <Modal.Body>
          <Stack gap="md" pb="xs">
            {diagramUrls.length > 0 ? (
              <Paper withBorder radius="md" p="sm" bg="var(--mantine-color-default-hover)">
                <Group align="flex-start" gap="md" wrap="wrap">
                  <Box className={classes.diagramFrame}>
                    <Image
                      src={diagramUrls[0]}
                      alt={`${plan.plan_name} floor plan diagram`}
                      fit="contain"
                    />
                  </Box>
                  <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
                    <Group gap="xs">
                      <Text fw={600} size="sm">
                        Floor plan diagram
                      </Text>
                      {diagramUrls.length > 1 && (
                        <Badge variant="outline" color="gray" size="sm">
                          1 of {diagramUrls.length}
                        </Badge>
                      )}
                    </Group>
                    <Text size="xs" c="dimmed">
                      Saved copy from {sourceDomain}, linked to this plan by the Source.
                    </Text>
                    {planUrl && (
                      <Anchor href={planUrl} target="_blank" rel="noreferrer" size="sm" fw={600}>
                        <Group gap={5} wrap="nowrap">
                          Open full-size on {sourceDomain}
                          <IconExternalLink size={13} />
                        </Group>
                      </Anchor>
                    )}
                  </Stack>
                </Group>
              </Paper>
            ) : (
              <Alert variant="light" color="gray" title="No floor plan diagram found">
                <Stack gap={6} align="flex-start">
                  <Text size="sm">
                    No image on this Source carried structured, card, or label evidence tying it to
                    this plan.
                  </Text>
                  {planUrl && (
                    <Anchor href={planUrl} target="_blank" rel="noreferrer" size="sm" fw={600}>
                      <Group gap={5} wrap="nowrap">
                        Open the plan page on {sourceDomain}
                        <IconExternalLink size={13} />
                      </Group>
                    </Anchor>
                  )}
                </Stack>
              </Alert>
            )}

            <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="sm" verticalSpacing="sm">
              <Fact
                label="Rent"
                value={formatRange(plan.rent_min, plan.rent_max, "$")}
                sub={plan.rent_min === plan.rent_max ? "single rate" : null}
              />
              <Fact
                label="All-in monthly"
                value={allIn === null ? "unknown" : `$${allIn.toLocaleString()}`}
                sub={score?.all_in_components?.estimated_total ? "includes estimates" : null}
              />
              <Fact label="Size" value={`${formatRange(plan.sqft_min, plan.sqft_max)} sqft`} />
              <Fact
                label="Deposit"
                value={plan.deposit === null ? "unknown" : `$${plan.deposit.toLocaleString()}`}
              />
              <Fact
                label="Available"
                value={plan.availability_date ?? "unknown"}
                sub={
                  plan.available_units === null
                    ? null
                    : `${plan.available_units} ${plan.available_units === 1 ? "unit" : "units"} available`
                }
              />
              <Fact
                label="Unit type"
                value={
                  plan.unit_types?.length
                    ? plan.unit_types.map((type) => type.replaceAll("_", " ")).join(", ")
                    : "unknown"
                }
              />
            </SimpleGrid>

            <Divider />

            <Stack gap="sm">
              <Text fz="xs" fw={700} tt="uppercase" lts="0.07em" c="dimmed">
                Amenities for this plan
              </Text>
              {amenities.length === 0 ? (
                <Text size="sm" c="dimmed">
                  No scoped unit amenities in this hunt&apos;s catalog yet.
                </Text>
              ) : (
                <>
                  {AMENITY_STATES.map((state) => (
                    <AmenityGroup
                      key={state}
                      state={state}
                      facts={groups[state]}
                      openKey={openEvidence}
                      onToggle={(key) => setOpenEvidence((prev) => (prev === key ? null : key))}
                    />
                  ))}
                  <Collapse expanded={openFact !== null} keepMounted={false}>
                    {openFact && <AmenityEvidence fact={openFact} />}
                  </Collapse>
                  {!openFact && (
                    <Text size="xs" c="dimmed">
                      Select ⓘ on any amenity for its evidence and Source.
                    </Text>
                  )}
                </>
              )}
            </Stack>

            <Divider />

            <Stack gap="sm">
              <Text fz="xs" fw={700} tt="uppercase" lts="0.07em" c="dimmed">
                Score breakdown for this plan
              </Text>
              {score ? (
                <CriterionBreakdown
                  huntId={huntId}
                  listingId={listingId}
                  breakdown={score.breakdown}
                  catalog={catalog}
                  extractions={extractions}
                  overrides={overrides}
                  floorPlanId={plan.id}
                  isMobile={isMobile}
                  members={members}
                />
              ) : (
                <Text size="sm" c="dimmed">
                  This plan has no score yet — ingestion may still be running (see Tasks).
                </Text>
              )}
            </Stack>

            <Text size="xs" c="dimmed">
              {planUrl ? (
                <Anchor href={planUrl} target="_blank" rel="noreferrer" size="xs" inherit>
                  {planUrl}
                </Anchor>
              ) : (
                "No Source link captured"
              )}
              {plan.source_native_id ? ` · Plan ID ${plan.source_native_id}` : ""}
              {source?.last_success_at
                ? ` · refreshed ${new Date(source.last_success_at).toLocaleDateString()}`
                : ""}
            </Text>
          </Stack>
        </Modal.Body>

        <Box className={classes.footer}>
          <Group gap="sm">
            {pinned ? (
              <>
                <Badge variant="light" leftSection={<IconPinFilled size={11} />}>
                  Pinned for {unitGroupLabel}
                </Badge>
                <Text size="xs" c="dimmed">
                  Shown on the Overview row for this group.
                </Text>
              </>
            ) : (
              <Button
                size="xs"
                leftSection={<IconPinFilled size={13} />}
                disabled={saving || readOnly}
                onClick={onTogglePin}
              >
                Pin for {unitGroupLabel}
              </Button>
            )}
            <Button size="xs" variant="default" ml="auto" onClick={onClose}>
              Close
            </Button>
          </Group>
        </Box>
      </Modal.Content>
    </Modal.Root>
  );
}
