// Unmatched Floor Plan diagrams (P3-SC5, workbook §7.2).
//
// A diagram the pipeline recognised but could not tie to a specific plan stays
// here, at the Property. It is deliberately NOT attached to every Floor Plan:
// showing one layout against all of them would be a confident lie, and the
// whole point of the scoped-fact work is that plan-specific claims stay
// plan-specific.
//
// The card renders only when such diagrams exist — an empty "unmatched" heading
// would imply a problem where there is none.
import { AspectRatio, Image, SimpleGrid, Stack, Text, UnstyledButton } from "@mantine/core";
import { useState } from "react";

import type { PropertyImage } from "./api";
import { ImageLightbox } from "./ImageLightbox";
import classes from "./UnmatchedDiagrams.module.css";

/** Diagrams with no current Floor Plan association, in stable display order. */
export function unmatchedDiagrams(images: PropertyImage[]): PropertyImage[] {
  return images.filter(
    (image) =>
      image.kind === "floor_plan_diagram" && (image.floorPlanAssociations ?? []).length === 0,
  );
}

export function UnmatchedDiagrams({ images }: { images: PropertyImage[] }) {
  const [lightbox, setLightbox] = useState<number | null>(null);
  const diagrams = unmatchedDiagrams(images);
  if (diagrams.length === 0) return null;

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        {diagrams.length === 1
          ? "One diagram on this Property could not be tied to a specific plan."
          : `${diagrams.length} diagrams on this Property could not be tied to a specific plan.`}{" "}
        They stay here rather than attaching to every floor plan.
      </Text>
      <SimpleGrid cols={{ base: 3, sm: 4 }} spacing="xs">
        {diagrams.map((image, index) => (
          <UnstyledButton
            key={image.id}
            className={classes.thumb}
            aria-label={`Open unmatched floor plan diagram ${index + 1} of ${diagrams.length}`}
            onClick={() => setLightbox(index)}
          >
            <AspectRatio ratio={4 / 3}>
              <Image src={image.url} alt="" loading="lazy" fit="contain" />
            </AspectRatio>
          </UnstyledButton>
        ))}
      </SimpleGrid>
      <ImageLightbox
        images={diagrams}
        index={lightbox}
        onNavigate={setLightbox}
        onClose={() => setLightbox(null)}
      />
    </Stack>
  );
}
