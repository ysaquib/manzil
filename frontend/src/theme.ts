// Mantine theme — the single styling seam (frontend/AGENTS.md): flat colors
// only, semantic roles picked here, components read tokens and never hardcode
// hex. Hierarchy comes from weight/size/gray, not decoration.
//
// Visual identity: "Dusk & clay" (DESIGN.md §20) — manzil as arriving
// somewhere at dusk. Primary is a muted dusk indigo; every neutral is warm
// (stone light mode, charcoal dark mode); clay is the lone warm accent
// (waiting on the user); status hues lean earthy (moss/olive/ochre) instead
// of electric. Headings are Literata (serif), body is Source Sans 3 (sans);
// both self-hosted via @fontsource-variable imports in main.tsx.
import { createTheme, rem, type CSSVariablesResolver } from "@mantine/core";
import { dusk, old_clay, gray, dark, green, lime, yellow, red } from "./colors";

const fontStackSans =
  "'Source Sans 3 Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
const fontStackSerif = "'Literata Variable', Georgia, 'Times New Roman', serif";

// Micro-interaction ease shared by hoverable chrome. Kept gentle; Mantine's
// own transitions honor respectReducedMotion, and a 140ms color fade is inert
// enough not to need a reduced-motion branch.
const hoverEase = {
  transition: "background-color 140ms ease, color 140ms ease, border-color 140ms ease",
};

export const theme = createTheme({
  primaryColor: "red",
  primaryShade: { light: 6, dark: 5 },
  autoContrast: true,
  respectReducedMotion: true,
  fontFamily: fontStackSans,
  defaultRadius: "md",
  headings: {
    fontFamily: fontStackSerif,
    fontWeight: "600",
    sizes: {
      h2: { fontSize: rem(24), lineHeight: "1.3" },
    },
  },
  colors: {
    // Dusk indigo — primary. Muted violet-leaning indigo; shade 6 carries
    // light mode, shade 5 dark mode (primaryShade above).
    dusk: dusk,
    clay: old_clay,
    gray: gray,
    dark: dark,
    green: green,
    lime: lime,
    yellow: yellow,
    red: red,

    // gray: colors.warm_stone,
    // dark: colors.dark_dusky,
    // clay: colors.clay,
    // red: colors.dusty_brick,
    // orange: colors.burnt_clay,
    // yellow: colors.muted_ochre,
    // lime: colors.olive,
    // green: colors.sage,
    // teal: colors.weathered_teal,
    // cyan: colors.fog_blue,
    // blue: colors.slate_blue,
    // indigo: colors.storm,
    // violet: colors.dusty_lavender,
    // grape: colors.muted_plum,
    // pink: colors.dusty_rose,
  },
  white: "#FFFEFB",
  shadows: {
    xs: "0 1px 2px rgba(43, 39, 33, 0.05)",
    sm: "0 1px 2px rgba(43, 39, 33, 0.05), 0 2px 6px rgba(43, 39, 33, 0.05)",
    md: "0 2px 4px rgba(43, 39, 33, 0.05), 0 6px 16px rgba(43, 39, 33, 0.07)",
    lg: "0 4px 8px rgba(43, 39, 33, 0.06), 0 12px 24px rgba(43, 39, 33, 0.08)",
    xl: "0 6px 12px rgba(43, 39, 33, 0.07), 0 20px 40px rgba(43, 39, 33, 0.09)",
  },
  components: {
    Badge: {
      defaultProps: { variant: "light" },
      // Sentence-case badges: quieter than Mantine's all-caps default, and
      // tabular figures keep score badges aligned in table columns.
      styles: {
        root: {
          textTransform: "none",
          letterSpacing: 0,
          fontWeight: 600,
          fontVariantNumeric: "tabular-nums",
        },
      },
    },
    Tooltip: { defaultProps: { withArrow: true } },
    Card: { defaultProps: { withBorder: true, radius: "md", padding: "md" } },
    Drawer: {
      defaultProps: {
        overlayProps: { opacity: 0.45 },
        transitionProps: { duration: 220, timingFunction: "ease" },
      },
    },
    Modal: {
      defaultProps: { transitionProps: { duration: 200, timingFunction: "ease" } },
    },
    Popover: { defaultProps: { transitionProps: { duration: 150 } } },
    HoverCard: { defaultProps: { transitionProps: { duration: 150 } } },
    Loader: { defaultProps: { type: "dots" } },
    Table: {
      // Numbers (rent, sqft, scores) align down a column.
      styles: { table: { fontVariantNumeric: "tabular-nums" } },
    },
    Button: { styles: { root: hoverEase } },
    ActionIcon: {
      defaultProps: { variant: "subtle" },
      styles: { root: hoverEase },
    },
    NavLink: {
      defaultProps: { variant: "subtle" },
      styles: { label: { fontWeight: 500 }, root: hoverEase },
    },
    AppShell: {
      styles: {
        main: { backgroundColor: "var(--mantine-color-body)" },
      },
    },
    Anchor: {
      defaultProps: { underline: "never" },
    },
  },
});

// Light-mode body sits on warm paper a step below card white, so Cards read
// as surfaces without heavier borders or shadows. Dark mode needs no
// override — the warm `dark` scale already supplies body/surfaces. Lives here
// (not main.tsx) so every color decision stays in the theme seam.
export const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {},
  light: {
    "--mantine-color-body": "#F6F3EE",
  },
  dark: {},
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
  active: "dusk" as const,
  /** waiting on the user (checkpoints) */
  waiting: "clay" as const,
  /** pinned/outline badges, secondary chrome */
  surface: "gray" as const,
  scoreBands: {
    high: "green",
    mid: "lime",
    low: "yellow",
    poor: "red",
  } as const,
};
