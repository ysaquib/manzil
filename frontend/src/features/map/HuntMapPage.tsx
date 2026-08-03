// Map view (`/h/:huntId/map`, §13.2 — §20 2026-07-26): every scored Unit Group
// in the hunt, plotted where it actually is.
//
// One pin is one Listing, because Unit Groups of a property share a building.
// A pin whose groups land in different score bands is sliced into those bands
// rather than averaged — the map must not invent a score. Clicking a
// single-group pin opens the detail Drawer straight away; a multi-group pin
// asks which group first, since "this property" is not a decision the rest of
// the app makes (§9.4: the compared/curated entity is the Unit Group).
//
// Filters come from the shared Overview state (features/listings/filterState),
// so the map and the table never disagree about what is in view.
import {
  Badge,
  Box,
  Card,
  Group,
  Modal,
  Stack,
  Text,
  Title,
  useComputedColorScheme,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconChevronRight } from "@tabler/icons-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { useGhostMode } from "../admin/useGhostMode";
import { useListings, useUnitGroupStates } from "../listings/api";
import { useOverviewFilters } from "../listings/filterState";
import { ListingDetailDrawer } from "../listings/ListingDetailDrawer";
import { useDrawerRoute } from "../listings/drawerRoute";
import { OverviewFilterBar } from "../listings/OverviewFilterBar";
import {
  analyzeOverviewFilters,
  buildRows,
  formatRange,
  sortRows,
} from "../listings/overviewRows";
import { propertyLocationLabel } from "../listings/locality";
import { formatScore, scoreLabel } from "../listings/scoreBands";
import {
  buildMapPoints,
  markerArt,
  pinColorTokens,
  pinSummary,
  svgDataUri,
  type MapPoint,
} from "./mapPoints";
import { MapFrame } from "./MapFrame";
import { markerOutline, scoreHex } from "./mapTheme";

export function HuntMapPage() {
  const { huntId = "" } = useParams();
  const { data: listings, isLoading } = useListings(huntId);
  const { data: unitGroupStates = [] } = useUnitGroupStates(huntId);
  const { isGhost } = useGhostMode(huntId);
  const { filters, setFilters, sharedFilters, canPublish, publish, publishPending } =
    useOverviewFilters();
  const isCompact = useMediaQuery("(max-width: 48em)") ?? false;

  const allRows = useMemo(
    () => buildRows(listings ?? [], unitGroupStates),
    [listings, unitGroupStates],
  );
  const filterResult = useMemo(
    () => analyzeOverviewFilters(allRows, filters),
    [allRows, filters],
  );
  const rows = useMemo(
    () => sortRows(filterResult.rows, { key: "score", dir: "desc" }),
    [filterResult.rows],
  );
  const { points, omissions } = useMemo(() => buildMapPoints(rows), [rows]);

  const cities = useMemo(
    () =>
      [...new Set((listings ?? []).map((l) => propertyLocationLabel(l.property)))].sort((a, b) =>
        a.localeCompare(b),
      ),
    [listings],
  );

  const [picker, setPicker] = useState<MapPoint | null>(null);
  // Drawer state is URL state (P3-16) — a pin opened from the map produces the
  // same shareable link the Overview does, filters included.
  const drawer = useDrawerRoute();

  const openDrawer = useCallback(
    (listingId: string, groupKey: string | null) => {
      setPicker(null);
      drawer.open(listingId, groupKey);
    },
    [drawer],
  );

  const onPinClick = useCallback(
    (point: MapPoint) => {
      if (point.groups.length === 1) openDrawer(point.listingId, point.groups[0].key);
      else setPicker(point);
    },
    [openDrawer],
  );

  return (
    <Stack gap="lg" style={{ minHeight: 0 }}>
      <PageHeader title="Map" description="Where this hunt's unit groups actually are" />

      <OverviewFilterBar
        filters={filters}
        onChange={setFilters}
        cities={cities}
        visibleCount={rows.length}
        totalCount={allRows.length}
        manualPinAlternateMatchCount={filterResult.manualPinAlternateMatchCount}
        sharedFilters={sharedFilters}
        canPublish={canPublish}
        onPublish={publish}
        publishPending={publishPending}
      />

      <MapCanvas points={points} onPinClick={onPinClick} isLoading={isLoading} compact={isCompact} />

      <Group justify="space-between" align="flex-start" gap="md" wrap="wrap">
        <Legend points={points} />
        <OmissionNote omissions={omissions} />
      </Group>

      <UnitGroupPicker
        point={picker}
        onClose={() => setPicker(null)}
        onSelect={(groupKey) => picker && openDrawer(picker.listingId, groupKey)}
      />

      <ListingDetailDrawer
        huntId={huntId}
        selection={drawer.renderSelection}
        opened={drawer.opened}
        onClose={drawer.close}
        onExited={drawer.onExited}
        isGhost={isGhost === true}
        filters={filters}
      />
    </Stack>
  );
}

// ── Map canvas ─────────────────────────────────────────────────────────────

function MapCanvas({
  points,
  onPinClick,
  isLoading,
  compact,
}: {
  points: MapPoint[];
  onPinClick: (point: MapPoint) => void;
  isLoading: boolean;
  compact: boolean;
}) {
  const dark = useComputedColorScheme("light") === "dark";
  const [map, setMap] = useState<google.maps.Map | null>(null);
  const markersRef = useRef(new Map<string, google.maps.Marker>());
  // Re-fit only when the plotted set changes — refitting on a repaint would
  // yank back a pan the user just made.
  const fittedRef = useRef<string>("");

  const onReady = useCallback((instance: google.maps.Map) => setMap(instance), []);

  useEffect(() => {
    if (!map) return;
    const markers = markersRef.current;
    const outline = markerOutline(dark);
    const live = new Set<string>();

    for (const point of points) {
      live.add(point.listingId);
      const colors = pinColorTokens(point.groups).map((token) => scoreHex(token, dark));
      const art = markerArt(colors, { outline });
      const icon: google.maps.Icon = {
        url: svgDataUri(art.svg),
        scaledSize: new google.maps.Size(art.width, art.height),
        anchor: new google.maps.Point(art.anchorX, art.anchorY),
      };
      const existing = markers.get(point.listingId);
      if (existing) {
        existing.setPosition({ lat: point.lat, lng: point.lng });
        existing.setIcon(icon);
        existing.setTitle(`${point.propertyName} — ${pinSummary(point.groups)}`);
        google.maps.event.clearListeners(existing, "click");
        existing.addListener("click", () => onPinClick(point));
      } else {
        const marker = new google.maps.Marker({
          map,
          position: { lat: point.lat, lng: point.lng },
          icon,
          title: `${point.propertyName} — ${pinSummary(point.groups)}`,
          zIndex: Math.round(point.bestScore * 10),
        });
        marker.addListener("click", () => onPinClick(point));
        markers.set(point.listingId, marker);
      }
    }

    for (const [id, marker] of markers) {
      if (live.has(id)) continue;
      marker.setMap(null);
      markers.delete(id);
    }

    const signature = points.map((p) => p.listingId).sort().join("|");
    if (points.length > 0 && signature !== fittedRef.current) {
      fittedRef.current = signature;
      const bounds = new google.maps.LatLngBounds();
      for (const point of points) bounds.extend({ lat: point.lat, lng: point.lng });
      map.fitBounds(bounds, 64);
      // A single pin fits to maximum zoom, which is disorienting.
      if (points.length === 1) {
        google.maps.event.addListenerOnce(map, "idle", () => {
          if ((map.getZoom() ?? 0) > 15) map.setZoom(15);
        });
      }
    }
  }, [map, points, dark, onPinClick]);

  useEffect(() => {
    const markers = markersRef.current;
    return () => {
      for (const marker of markers.values()) marker.setMap(null);
      markers.clear();
    };
  }, []);

  return (
    <MapFrame
      height={compact ? 420 : "min(88vh, 44rem)"}
      onReady={onReady}
      emptyLabel={
        isLoading
          ? null
          : points.length === 0
            ? "No scored listings to plot. Loosen the filters, or wait for ingestion to finish scoring."
            : null
      }
    />
  );
}

// ── Legend + footnote ──────────────────────────────────────────────────────

function Legend({ points }: { points: MapPoint[] }) {
  const dark = useComputedColorScheme("light") === "dark";
  const bands = useMemo(() => {
    const byToken = new Map<string, { label: string; best: number }>();
    for (const point of points) {
      for (const group of point.groups) {
        const current = byToken.get(group.colorToken);
        if (!current || group.score > current.best) {
          byToken.set(group.colorToken, { label: scoreLabel(group.score), best: group.score });
        }
      }
    }
    return [...byToken.entries()].sort((a, b) => b[1].best - a[1].best);
  }, [points]);

  if (bands.length === 0) return <Box />;

  return (
    <Group gap="md" wrap="wrap">
      {bands.map(([token, { label }]) => (
        <Group key={token} gap={6} wrap="nowrap">
          <Box
            w={10}
            h={10}
            style={{ borderRadius: "50%", backgroundColor: scoreHex(token, dark) }}
          />
          <Text size="xs" c="dimmed">
            {label}
          </Text>
        </Group>
      ))}
      <Text size="xs" c="dimmed">
        A sliced pin scores differently by unit group.
      </Text>
    </Group>
  );
}

function OmissionNote({
  omissions,
}: {
  omissions: { unmapped: number; unscored: number };
}) {
  const parts: string[] = [];
  if (omissions.unscored > 0) {
    parts.push(`${omissions.unscored} not scored yet`);
  }
  if (omissions.unmapped > 0) {
    parts.push(`${omissions.unmapped} without a mapped location`);
  }
  if (parts.length === 0) return null;
  const total = omissions.unmapped + omissions.unscored;
  return (
    <Text size="xs" c="dimmed">
      {total} listing{total === 1 ? "" : "s"} not on the map — {parts.join(", ")}.
    </Text>
  );
}

// ── Unit Group picker ──────────────────────────────────────────────────────

function UnitGroupPicker({
  point,
  onClose,
  onSelect,
}: {
  point: MapPoint | null;
  onClose: () => void;
  onSelect: (groupKey: string) => void;
}) {
  return (
    <Modal
      opened={point !== null}
      onClose={onClose}
      title={
        point ? (
          <Stack gap={0}>
            <Title order={5}>{point.propertyName}</Title>
            <Text size="xs" c="dimmed">
              {point.address}
            </Text>
          </Stack>
        ) : null
      }
      zIndex={250}
    >
      <Stack gap="xs">
        <Text size="sm" c="dimmed">
          This property has {point?.groups.length} unit groups. Which one?
        </Text>
        {point?.groups.map((group) => (
          <Card
            key={group.key}
            component="button"
            withBorder
            padding="sm"
            onClick={() => onSelect(group.key)}
            style={{ cursor: "pointer", textAlign: "left", width: "100%" }}
          >
            <Group justify="space-between" wrap="nowrap" gap="sm">
              <Stack gap={2} style={{ minWidth: 0 }}>
                <Text size="sm" fw={600}>
                  {group.label}
                </Text>
                <Text size="xs" c="dimmed">
                  {formatRange(group.rentMin, group.rentMax, "$")}
                  {group.planCount > 1 ? ` · ${group.planCount} plans` : ""}
                </Text>
              </Stack>
              <Group gap={6} wrap="nowrap">
                <Badge color={group.colorToken} variant="light" ff="monospace">
                  {formatScore(group.score)}
                </Badge>
                <IconChevronRight size={15} stroke={1.5} color="var(--mantine-color-dimmed)" />
              </Group>
            </Group>
          </Card>
        ))}
      </Stack>
    </Modal>
  );
}
