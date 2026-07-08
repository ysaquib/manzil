// Mantine theme — the single styling seam (frontend/AGENTS.md): flat colors
// only, semantic roles picked here, components read tokens and never hardcode
// hex. Hierarchy comes from weight/size/gray, not decoration.
import { createTheme, rem } from "@mantine/core";

export const theme = createTheme({
  primaryColor: "indigo",
  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
  defaultRadius: "md",
  headings: {
    fontWeight: "600",
    sizes: {
      h2: { fontSize: rem(24) },
    },
  },
  components: {
    Badge: { defaultProps: { variant: "light" } },
    Tooltip: { defaultProps: { withArrow: true } },
    Card: { defaultProps: { withBorder: true, radius: "md" } },
    Drawer: { defaultProps: { overlayProps: { opacity: 0.35 } } },
  },
});

// Semantic color roles (Mantine palette names). Components import these
// instead of restating palette choices; swap the role here, not per usage.
export const semantic = {
  /** estimated / unverified figures (all-in cost est. portion, unknown fees) */
  estimated: "yellow" as const,
  /** human-entered values: overrides, manual fee entries */
  manual: "grape" as const,
  /** destructive actions and gate firings */
  danger: "red" as const,
  /** running/active state */
  active: "indigo" as const,
  /** waiting on the user (checkpoints) */
  waiting: "orange" as const,
};
