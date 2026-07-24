// Compare-view photo strip: a @mantine/carousel multi-slide strip of the
// collected property images. Clicking a photo opens the full-screen lightbox
// (ImageLightbox — a zoom viewer, kept custom). The strip scrolls in its own
// container (no page horizontal scroll).
import { Box, Skeleton, Text, UnstyledButton } from "@mantine/core";
import { Carousel } from "@mantine/carousel";
import type { EmblaCarouselType } from "embla-carousel";
import { useCallback, useEffect, useState } from "react";

import type { PropertyImage } from "./api";
import { ImageLightbox } from "./ImageLightbox";

const STRIP_HEIGHT = 220;

export function PropertyImageCarousel({
  images,
  loading,
}: {
  images: PropertyImage[];
  loading: boolean;
}) {
  const [embla, setEmbla] = useState<EmblaCarouselType | null>(null);
  const [index, setIndex] = useState(0);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);

  const onSelect = useCallback((api: EmblaCarouselType) => setIndex(api.selectedScrollSnap()), []);
  useEffect(() => {
    if (!embla) return;
    onSelect(embla);
    embla.on("select", onSelect);
    return () => {
      embla.off("select", onSelect);
    };
  }, [embla, onSelect]);

  if (loading) {
    return <Skeleton height={STRIP_HEIGHT} radius="md" />;
  }
  if (images.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No photos collected yet — the image pass runs during ingestion.
      </Text>
    );
  }

  const many = images.length > 1;
  return (
    <Box pos="relative">
      <Carousel
        getEmblaApi={setEmbla}
        withControls={many}
        withIndicators={false}
        height={STRIP_HEIGHT}
        slideSize="78%"
        slideGap="xs"
        emblaOptions={{ align: "start" }}
        previousControlProps={{ "aria-label": "previous photos" }}
        nextControlProps={{ "aria-label": "next photos" }}
      >
        {images.map((image, i) => (
          <Carousel.Slide key={image.id}>
            <UnstyledButton
              onClick={() => setLightboxIndex(i)}
              aria-label={`open photo ${i + 1} of ${images.length}`}
              style={{
                display: "block",
                width: "100%",
                height: "100%",
                cursor: "zoom-in",
                borderRadius: "var(--mantine-radius-md)",
                overflow: "hidden",
              }}
            >
              <img
                src={image.url}
                alt={`listing photo ${i + 1} of ${images.length}`}
                loading="lazy"
                style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
              />
            </UnstyledButton>
          </Carousel.Slide>
        ))}
      </Carousel>
      {many && (
        <Text
          size="xs"
          c="white"
          style={{
            position: "absolute",
            right: 10,
            bottom: 8,
            background: "rgba(0, 0, 0, 0.55)",
            borderRadius: 999,
            padding: "1px 8px",
            pointerEvents: "none",
          }}
        >
          {index + 1} / {images.length}
        </Text>
      )}

      <ImageLightbox
        images={images}
        index={lightboxIndex}
        onNavigate={setLightboxIndex}
        onClose={() => setLightboxIndex(null)}
      />
    </Box>
  );
}
