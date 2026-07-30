import { Box } from "@mantine/core";
import type { ReactNode } from "react";

const OPTION_ROW_STYLE = {
  display: "grid",
  // gridTemplateColumns: "minmax(0, 1fr) 108px 26px 26px",
  gridTemplateColumns: "minmax(0, 1fr) 108px 50px",
  gap: "var(--mantine-spacing-xs)",
  alignItems: "center",
} as const;

export function OptionGridRow({ children }: { children: ReactNode }) {
  return <Box style={OPTION_ROW_STYLE}>{children}</Box>;
}
