// Full-screen photo viewer for the detail drawer's carousel: arrow/keyboard
// navigation, fit ↔ full-size zoom (click the photo or the zoom button),
// counter, close on Escape/backdrop. Dependency-free like the carousel.
import { ActionIcon, Box, Group, Modal, Text } from "@mantine/core";
import {
  IconChevronLeft,
  IconChevronRight,
  IconX,
  IconZoomIn,
  IconZoomOut,
} from "@tabler/icons-react";
import { useEffect, useState } from "react";

import type { PropertyImage } from "./api";

export function ImageLightbox({
  images,
  index,
  onNavigate,
  onClose,
}: {
  images: PropertyImage[];
  /** Open at this index; null renders the modal closed. */
  index: number | null;
  onNavigate: (nextIndex: number) => void;
  onClose: () => void;
}) {
  const [zoomed, setZoomed] = useState(false);
  const opened = index !== null && images.length > 0;
  const activeIndex = Math.min(index ?? 0, Math.max(0, images.length - 1));
  const current = opened ? images[activeIndex] : null;

  // Reset to fit view whenever the photo changes — a zoom is a per-photo look.
  useEffect(() => {
    setZoomed(false);
  }, [index]);

  useEffect(() => {
    if (!opened) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight") onNavigate((activeIndex + 1) % images.length);
      if (event.key === "ArrowLeft") onNavigate((activeIndex - 1 + images.length) % images.length);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [opened, activeIndex, images.length, onNavigate]);

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      fullScreen
      padding={0}
      withCloseButton={false}
      zIndex={400}
      transitionProps={{ transition: "fade", duration: 150 }}
      styles={{
        content: { background: "rgba(12, 10, 9, 0.95)" },
        body: { height: "100dvh", display: "flex", flexDirection: "column" },
      }}
    >
      {current && (
        <>
          <Group
            justify="space-between"
            px="md"
            py="sm"
            style={{ position: "absolute", top: 0, left: 0, right: 0, zIndex: 1 }}
          >
            <Text size="sm" c="gray.4" style={{ fontVariantNumeric: "tabular-nums" }}>
              {activeIndex + 1} / {images.length}
            </Text>
            <Group gap="xs">
              <ActionIcon
                variant="default"
                radius="xl"
                size="lg"
                aria-label={zoomed ? "zoom to fit" : "zoom in"}
                onClick={() => setZoomed((z) => !z)}
              >
                {zoomed ? (
                  <IconZoomOut size={18} stroke={1.5} />
                ) : (
                  <IconZoomIn size={18} stroke={1.5} />
                )}
              </ActionIcon>
              <ActionIcon
                variant="default"
                radius="xl"
                size="lg"
                aria-label="close photo viewer"
                onClick={onClose}
              >
                <IconX size={18} stroke={1.5} />
              </ActionIcon>
            </Group>
          </Group>

          <Box
            style={{
              flex: 1,
              minHeight: 0,
              display: "flex",
              alignItems: zoomed ? "flex-start" : "center",
              justifyContent: zoomed ? "flex-start" : "center",
              overflow: zoomed ? "auto" : "hidden",
              padding: zoomed ? 0 : "48px 16px 16px",
            }}
            onClick={(event) => {
              // Backdrop click closes; clicks on the photo toggle zoom below.
              if (event.target === event.currentTarget) onClose();
            }}
          >
            <img
              src={current.url}
              alt={`listing photo ${activeIndex + 1} of ${images.length}`}
              onClick={() => setZoomed((z) => !z)}
              style={
                zoomed
                  ? {
                      // Zoom is relative to the viewport (not natural pixels) so
                      // small normalized WebPs still zoom instead of shrinking.
                      height: "170%",
                      width: "auto",
                      maxWidth: "none",
                      maxHeight: "none",
                      cursor: "zoom-out",
                      margin: "auto",
                    }
                  : {
                      width: "auto",
                      height: "90%",
                      maxWidth: "100%",
                      objectFit: "contain",
                      cursor: "zoom-in",
                      borderRadius: "var(--mantine-radius-sm)",
                    }
              }
            />
          </Box>

          {images.length > 1 && (
            <>
              <ActionIcon
                variant="default"
                radius="xl"
                size="xl"
                aria-label="previous photo"
                onClick={() => onNavigate((activeIndex - 1 + images.length) % images.length)}
                style={{ position: "absolute", left: 16, top: "50%", transform: "translateY(-50%)" }}
              >
                <IconChevronLeft size={20} stroke={1.5} />
              </ActionIcon>
              <ActionIcon
                variant="default"
                radius="xl"
                size="xl"
                aria-label="next photo"
                onClick={() => onNavigate((activeIndex + 1) % images.length)}
                style={{ position: "absolute", right: 16, top: "50%", transform: "translateY(-50%)" }}
              >
                <IconChevronRight size={20} stroke={1.5} />
              </ActionIcon>
            </>
          )}
        </>
      )}
    </Modal>
  );
}
