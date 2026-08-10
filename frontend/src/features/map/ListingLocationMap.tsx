// Drawer "Location" card (§13.2): where this property actually is, with the
// displayed Unit Group's band colour on the pin so the map agrees with the
// score the reader is looking at.
//
// A property has no coordinates until a run geocodes it (§12 forever-cache is
// written by DEDUPE only-when-null), so "not mapped yet" is an ordinary state,
// not an error — the address and the Google Maps deep link stay useful either way.
import { Anchor, Group, Stack, Text, useComputedColorScheme } from "@mantine/core";
import { IconExternalLink, IconMapPin } from "@tabler/icons-react";
import { useCallback, useRef } from "react";

import { isDemo } from "../../lib/demo";
import { googleMapsLink } from "../../lib/googleMaps";
import { scoreColor } from "../listings/scoreBands";
import type { Property } from "../listings/types";
import { propertyBasemap } from "./demoBasemap";
import { markerArt, svgDataUri } from "./mapPoints";
import { MapFrame } from "./MapFrame";
import { markerOutline, scoreHex } from "./mapTheme";

const ZOOM = 15;

export function ListingLocationMap({
  property,
  score,
}: {
  property: Property;
  /** Displayed Unit Group's total, or null when the row isn't scored. */
  score: number | null;
}) {
  const dark = useComputedColorScheme("light") === "dark";
  const markerRef = useRef<google.maps.Marker | null>(null);
  const hasCoords = typeof property.lat === "number" && typeof property.lng === "number";
  const position = hasCoords ? { lat: property.lat!, lng: property.lng! } : null;

  const onReady = useCallback(
    (map: google.maps.Map) => {
      if (!position) return;
      map.setOptions({ center: position, zoom: ZOOM });
      const color =
        score === null
          ? scoreHex("gray", dark)
          : scoreHex(scoreColor(score), dark);
      const art = markerArt([color], { outline: markerOutline(dark) });
      const icon: google.maps.Icon = {
        url: svgDataUri(art.svg),
        scaledSize: new google.maps.Size(art.width, art.height),
        anchor: new google.maps.Point(art.anchorX, art.anchorY),
      };
      if (markerRef.current) markerRef.current.setIcon(icon);
      else {
        markerRef.current = new google.maps.Marker({
          map,
          position,
          icon,
          title: property.name,
        });
      }
    },
    // Depend on the coordinate *values*, not the `position` object literal
    // that is rebuilt every render.
    [property.lat, property.lng, property.name, score, dark],
  );

  // The still is captured centred on this Property, so its pin is the container
  // centre by construction — no projection, and it stays correct at any size.
  const basemap = isDemo() && hasCoords ? propertyBasemap(property.name, dark) : null;
  const demoPin = markerArt(
    [score === null ? scoreHex("gray", dark) : scoreHex(scoreColor(score), dark)],
    { outline: markerOutline(dark) },
  );

  return (
    <Stack gap="xs">
      <MapFrame
        height={200}
        onReady={onReady}
        demoBasemap={basemap}
        demoOverlay={
          basemap
            ? () => (
                <img
                  src={svgDataUri(demoPin.svg)}
                  alt={property.name}
                  width={demoPin.width}
                  height={demoPin.height}
                  style={{
                    position: "absolute",
                    left: "50%",
                    top: "50%",
                    // Anchor the tip on the coordinate, exactly as the real
                    // marker's `anchor` does.
                    transform: `translate(${-demoPin.anchorX}px, ${-demoPin.anchorY}px)`,
                    pointerEvents: "none",
                  }}
                />
              )
            : undefined
        }
        emptyLabel={
          hasCoords
            ? null
            : "Not mapped yet — coordinates arrive when a run geocodes this property."
        }
      />
      {/* The address itself is already in the drawer header — repeating it
          here would be noise, so this row is just the escape hatch. */}
      <Group justify="space-between" gap="xs" wrap="nowrap" align="center">
        <Group gap={7} wrap="nowrap" style={{ minWidth: 0 }}>
          <IconMapPin size={14} stroke={2} color="var(--mantine-color-dimmed)" />
          <Text size="xs" c="dimmed">
            {hasCoords ? "Geocoded location" : "Address only"}
          </Text>
        </Group>
        <Anchor
          href={googleMapsLink(property.canonical_address, property.lat, property.lng)}
          target="_blank"
          rel="noreferrer noopener"
          size="sm"
          style={{ whiteSpace: "nowrap" }}
        >
          <Group gap={4} wrap="nowrap">
            Open in Maps
            <IconExternalLink size={13} stroke={2} />
          </Group>
        </Anchor>
      </Group>
    </Stack>
  );
}
