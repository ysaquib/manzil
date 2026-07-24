import { ActionIcon, Skeleton, Text, UnstyledButton } from "@mantine/core";
import { IconChevronLeft, IconChevronRight } from "@tabler/icons-react";
import { useState } from "react";
import type { PropertyImage } from "./api";
import { ImageLightbox } from "./ImageLightbox";
import classes from "./DrawerImageGallery.module.css";

export function DrawerImageGallery({ images, loading }: { images: PropertyImage[]; loading: boolean }) {
  const [index, setIndex] = useState(0);
  const [lightbox, setLightbox] = useState<number | null>(null);
  if (loading) return <Skeleton className={classes.primary} />;
  if (images.length === 0) {
    return <Text size="sm" c="dimmed">No photos collected yet — the image pass runs during ingestion.</Text>;
  }
  const clamp = (i: number) => (i + images.length) % images.length;
  const current = images[Math.min(index, images.length - 1)];
  return (
    <div className={classes.gallery}>
      <div className={classes.primaryWrap}>
        <UnstyledButton
          className={classes.primaryBtn}
          onClick={() => setLightbox(index)}
          aria-label={`open photo ${index + 1} of ${images.length}`}
        >
          <img className={classes.primary} src={current.url} alt={`listing photo ${index + 1} of ${images.length}`} loading="lazy" />
        </UnstyledButton>
        {images.length > 1 && (
          <>
            <ActionIcon className={`${classes.nav} ${classes.prev}`} radius="xl"
              aria-label="previous photo" onClick={() => setIndex(clamp(index - 1))}>
              <IconChevronLeft size={16} stroke={2} />
            </ActionIcon>
            <ActionIcon className={`${classes.nav} ${classes.next}`} radius="xl"
              aria-label="next photo" onClick={() => setIndex(clamp(index + 1))}>
              <IconChevronRight size={16} stroke={2} />
            </ActionIcon>
            <span className={classes.counter}>{index + 1} / {images.length}</span>
          </>
        )}
      </div>
      {images.length > 1 && (
        <div className={classes.film}>
          {images.map((img, i) => (
            <button key={img.id} type="button"
              className={`${classes.thumb} ${i === index ? classes.active : ""}`}
              aria-label={`show photo ${i + 1}`} aria-pressed={i === index}
              onClick={() => setIndex(i)}>
              <img src={img.url} alt="" />
            </button>
          ))}
        </div>
      )}
      <ImageLightbox images={images} index={lightbox} onNavigate={setLightbox} onClose={() => setLightbox(null)} />
    </div>
  );
}
