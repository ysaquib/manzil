// Listing photo strip (P3-7a gallery): scroll-snap carousel of the collected
// property images, above the score breakdown in the drawer. Dependency-free —
// a snap strip with chevron paging, no embla. Images are signed-URL WebPs
// from the private bucket; the strip scrolls in its own container (no page
// horizontal scroll).
import { ActionIcon, Box, Group, Skeleton, Text } from "@mantine/core";
import { IconChevronLeft, IconChevronRight } from "@tabler/icons-react";
import { useRef, useState } from "react";

import type { PropertyImage } from "./api";

const STRIP_HEIGHT = 170;

export function PropertyImageCarousel({
  images,
  loading,
}: {
  images: PropertyImage[];
  loading: boolean;
}) {
  const strip = useRef<HTMLDivElement | null>(null);
  const [index, setIndex] = useState(0);

  if (loading) {
    return (
      <Group gap="xs" wrap="nowrap">
        <Skeleton height={STRIP_HEIGHT} width={220} radius="md" />
        <Skeleton height={STRIP_HEIGHT} width={220} radius="md" />
      </Group>
    );
  }
  if (images.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No photos collected yet — the image pass runs during ingestion.
      </Text>
    );
  }

  const page = (dir: 1 | -1) => {
    const el = strip.current;
    if (!el) return;
    el.scrollBy({ left: dir * el.clientWidth * 0.85, behavior: "smooth" });
  };

  const onScroll = () => {
    const el = strip.current;
    if (!el || el.scrollWidth <= el.clientWidth) return;
    const progress = el.scrollLeft / (el.scrollWidth - el.clientWidth);
    setIndex(Math.min(images.length - 1, Math.round(progress * (images.length - 1))));
  };

  return (
    <Box pos="relative">
      <Box
        ref={strip}
        onScroll={onScroll}
        style={{
          display: "flex",
          gap: 8,
          overflowX: "auto",
          scrollSnapType: "x mandatory",
          scrollbarWidth: "none",
          borderRadius: "var(--mantine-radius-md)",
        }}
      >
        {images.map((image, i) => (
          <img
            key={image.id}
            src={image.url}
            alt={`listing photo ${i + 1} of ${images.length}`}
            loading="lazy"
            style={{
              height: STRIP_HEIGHT,
              width: "auto",
              maxWidth: "85%",
              objectFit: "cover",
              borderRadius: "var(--mantine-radius-md)",
              scrollSnapAlign: "start",
              flexShrink: 0,
            }}
          />
        ))}
      </Box>
      {images.length > 1 && (
        <>
          <ActionIcon
            variant="default"
            radius="xl"
            size="md"
            aria-label="previous photos"
            onClick={() => page(-1)}
            style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)" }}
          >
            <IconChevronLeft size={16} stroke={1.5} />
          </ActionIcon>
          <ActionIcon
            variant="default"
            radius="xl"
            size="md"
            aria-label="next photos"
            onClick={() => page(1)}
            style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)" }}
          >
            <IconChevronRight size={16} stroke={1.5} />
          </ActionIcon>
          <Text
            size="xs"
            c="white"
            style={{
              position: "absolute",
              right: 10,
              bottom: 8,
              background: "rgba(0,0,0,0.55)",
              borderRadius: 999,
              padding: "1px 8px",
            }}
          >
            {index + 1} / {images.length}
          </Text>
        </>
      )}
    </Box>
  );
}
