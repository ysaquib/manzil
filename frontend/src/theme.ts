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
  primaryColor: "dusk",
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
    dusk: [
      "#F0F0F9",
      "#E2E2F3",
      "#CBCBE9",
      "#AEAEDC",
      "#9292CD",
      "#7B7BBF",
      "#5C5CAA",
      "#4C4C90",
      "#3D3D75",
      "#30305C",
    ],
    // Clay — the supporting warm accent. Reserved for "waiting on the user"
    // (checkpoints); deliberately more amber than red so it never reads as
    // danger.
    clay: [
      "#FAF0EA",
      "#F4DFD2",
      "#EAC5AE",
      "#DDA687",
      "#D08B65",
      "#C57749",
      "#B96438",
      "#9C512D",
      "#7D4024",
      "#5F311C",
    ],
    // Warm stone replaces Mantine's cool gray: borders, dimmed text, striped
    // rows, and secondary chrome all warm up through this one scale.
    gray: [
      "#F8F6F2",
      "#F0EDE7",
      "#E6E2DA",
      "#D6D1C7",
      "#C0BAAE",
      "#A39D90",
      "#7E7869",
      "#635D51",
      "#453F36",
      "#2B2721",
    ],
    // Warm charcoal replaces Mantine's blue-black dark scale. Same role
    // indices as stock (6 = surfaces, 7 = body, 4 = borders, 0 = text).
    dark: [
      "#CDC9C3",
      "#BBB6AF",
      "#8B867E",
      "#6F6A62",
      "#48443E",
      "#3D3933",
      "#302C27",
      "#262320",
      "#201D1A",
      "#161412",
    ],
    // Status hues re-tuned earthy, same names so `semantic` and component
    // code stay untouched: green→moss, lime→olive, yellow→ochre, red stays
    // alarming but loses the neon edge.
    green: [
      "#F2F6EC",
      "#E3EDD6",
      "#CBDDB3",
      "#AECA8C",
      "#93B96B",
      "#7FAC54",
      "#679441",
      "#547B34",
      "#44642A",
      "#354E21",
    ],
    lime: [
      "#F7F7E8",
      "#EEEECC",
      "#DEDFA5",
      "#CCCE7C",
      "#BCBF5B",
      "#AAAE41",
      "#8F9330",
      "#767A27",
      "#5F6220",
      "#4A4C1A",
    ],
    yellow: [
      "#FBF4E6",
      "#F6E7C6",
      "#EFD69D",
      "#E6C170",
      "#DEAF4B",
      "#D9A233",
      "#BC8A22",
      "#9C711C",
      "#7D5A17",
      "#614613",
    ],
    red: [
      "#FBEFEC",
      "#F6DCD6",
      "#EEBFB4",
      "#E39D8C",
      "#D77D67",
      "#CE6249",
      "#BF4B3B",
      "#A23D30",
      "#833125",
      "#66261D",
    ],
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
