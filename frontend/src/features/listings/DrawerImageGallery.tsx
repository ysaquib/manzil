import { AspectRatio, Box, Image, Skeleton, Text } from "@mantine/core";
import { Carousel } from "@mantine/carousel";
import type { EmblaCarouselType } from "embla-carousel";
import { useCallback, useEffect, useState } from "react";

import type { PropertyImage } from "./api";
import { ImageLightbox } from "./ImageLightbox";
import classes from "./DrawerImageGallery.module.css";

// Drawer photo gallery: a @mantine/carousel primary (16:10, cover-cropped) with
// a thumbnail filmstrip that scrolls it. Clicking the primary opens the
// full-screen zoom viewer (ImageLightbox — kept custom, it is a zoom viewer,
// not a carousel).
export function DrawerImageGallery({ images, loading }: { images: PropertyImage[]; loading: boolean }) {
  const [embla, setEmbla] = useState<EmblaCarouselType | null>(null);
  const [index, setIndex] = useState(0);
  const [lightbox, setLightbox] = useState<number | null>(null);

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
    return (
      <AspectRatio ratio={16 / 10}>
        <Skeleton radius="md" />
      </AspectRatio>
    );
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
    <div className={classes.gallery}>
      <div className={classes.primaryWrap}>
        <Carousel
          getEmblaApi={setEmbla}
          withControls={many}
          withIndicators={false}
          emblaOptions={{ loop: true }}
          previousControlProps={{ "aria-label": "previous photo" }}
          nextControlProps={{ "aria-label": "next photo" }}
          classNames={{ viewport: classes.viewport, control: classes.control }}
        >
          {images.map((img, i) => (
            <Carousel.Slide 
              key={img.id}
              w="100%"
              // h="100px"
            >
              {/* <button
                type="button"
                className={classes.primaryBtn}
                aria-label={`open photo ${i + 1} of ${images.length}`}
                onClick={() => setLightbox(i)}
              > */}
                <Image
                  src={img.url}
                  alt={`listing photo ${i + 1} of ${images.length}`}
                  loading="lazy"
                  className={classes.primary}
                  // width={100}
                  // height={100}
                />
                {/* <img
                  // className={classes.primary}
                  src={img.url}
                  alt={`listing photo ${i + 1} of ${images.length}`}
                  loading="lazy"
                /> */}
              {/* </button> */}
            </Carousel.Slide>
          ))}
        </Carousel>
        {many && <span className={classes.counter}>{index + 1} / {images.length}</span>}
      </div>
      {many && (
        <div className={classes.film}>
          {images.map((img, i) => (
            <Box
              key={img.id}
              className={`${classes.thumb} ${i === index ? classes.active : ""}`}
              aria-label={`show photo ${i + 1}`}
              aria-pressed={i === index}
              onClick={() => embla?.scrollTo(i)}
            >
              <Image src={img.url} alt="" />
            </Box>
          ))}
        </div>
      )}
      <ImageLightbox images={images} index={lightbox} onNavigate={setLightbox} onClose={() => setLightbox(null)} />
    </div>
  );
}
