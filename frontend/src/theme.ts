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
import {
  createTheme,
  rem,
  virtualColor,
  type ActionIconProps,
  type CSSVariablesResolver,
  type MantineTheme,
} from "@mantine/core";
import { clayColors } from "./colors";

const fontStackSans =
  "'Source Sans 3 Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
const fontStackSerif = "'Literata Variable', Georgia, 'Times New Roman', serif";
const fontStackMono = "'JetBrains Mono', monospace";

// Micro-interaction ease shared by hoverable chrome. Kept gentle; Mantine's
// own transitions honor respectReducedMotion, and a 140ms color fade is inert
// enough not to need a reduced-motion branch.
const hoverEase = {
  transition: "background-color 140ms ease, color 140ms ease, border-color 140ms ease",
};

export const theme = createTheme({
  primaryColor: "dusky",
  primaryShade: { light: 7, dark: 5 },
  autoContrast: true,
  respectReducedMotion: true,
  fontFamily: fontStackSans,
  fontFamilyMonospace: fontStackMono,
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
    // dusk: dusk,
    // clay: old_clay,
    // gray: gray,
    // dark: dark,
    // green: green,
    // lime: lime,
    // yellow: yellow,
    // red: red,

    dusky: clayColors.dusky,
    gray: clayColors.warm_stone,
    dark: clayColors.dark_dusky,
    red: clayColors.dusty_brick,
    orange: clayColors.burnt_clay,
    yellow: clayColors.muted_ochre,
    lime: clayColors.olive,
    green: clayColors.sage,
    teal: clayColors.weathered_teal,
    cyan: clayColors.fog_blue,
    blue: clayColors.slate_blue,
    indigo: clayColors.storm,
    violet: clayColors.dusty_lavender,
    grape: clayColors.muted_plum,
    pink: clayColors.dusty_rose,
    
    manual: clayColors.muted_plum,

    primary: virtualColor({
      name: "primary",
      light: "grape",
      dark: "grape",
    }),

    accent: virtualColor({
      name: "accent",
      light: "orange",
      dark: "orange",
    }),

    surface: virtualColor({
      name: "surface",
      light: "gray",
      dark: "dark",
    }),


    scoreHighest: clayColors.fog_blue,
    scoreHigh: clayColors.sage,
    scoreGood: clayColors.olive,
    scoreMid: clayColors.muted_ochre,
    scoreLow: clayColors.burnt_clay,
    scorePoor: clayColors.dusty_brick,
    scorePoorest: clayColors.dark_dusky,
  },
  white: "#FFFEFB",
  shadows: {
    xs: "0 1px 2px rgba(43, 39, 33, 0.15)",
    sm: "0 1px 2px rgba(43, 39, 33, 0.15), 0 2px 6px rgba(43, 39, 33, 0.05)",
    md: "0 2px 4px rgba(43, 39, 33, 0.15), 0 6px 16px rgba(43, 39, 33, 0.07)",
    lg: "0 4px 8px rgba(43, 39, 33, 0.16), 0 12px 24px rgba(43, 39, 33, 0.08)",
    xl: "0 6px 12px rgba(43, 39, 33, 0.17), 0 20px 40px rgba(43, 39, 33, 0.09)",
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
      styles: {
        table: { fontVariantNumeric: "tabular-nums" },
        scrollContainer: {
          overscrollBehaviorInline: "contain",
          WebkitOverflowScrolling: "touch",
          scrollBehavior: "smooth",
        },
      },
    },
    Button: { styles: { root: hoverEase } },
    ActionIcon: {
      defaultProps: { variant: "subtle" },
      styles: (_theme: MantineTheme, props: ActionIconProps) => ({
        root: {
          ...hoverEase,
          ...(props.color === "gray" || props.color === undefined
            ? {
                color: "var(--mantine-color-dimmed)",
                "&:hover": { backgroundColor: "var(--mantine-color-default-hover)" },
              }
            : {}),
        },
      }),
    },
    CloseButton: {
      styles: {
        root: {
          ...hoverEase,
          color: "var(--mantine-color-dimmed)",
          "&:hover": { backgroundColor: "var(--mantine-color-default-hover)" },
        },
      },
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
  dark: {
    // "--mantine-color-body": "var(--mantine-color-dark-8)",
    // "--table-striped-color": "var(--mantine-color-dark-7)",
    // "--table-highlight-on-hover-color": "var(--mantine-color-dark-2)",
    // "#1B181A",
    // "#131112",
  },
});

// Semantic color roles (Mantine palette names). Components import these
// instead of restating palette choices; swap the role here, not per usage.
// export const semantic = {
//   /** estimated / unverified figures (all-in cost est. portion, unknown fees) */
//   estimated: "yellow" as const,
//   /** human-entered values: overrides, manual fee entries */
//   manual: "grape" as const,
//   /** destructive actions and gate firings */
//   danger: "red" as const,
//   /** running/active state */
//   active: "dusky" as const,
//   /** waiting on the user (checkpoints) */
//   waiting: "teal" as const,
//   /** pinned/outline badges, secondary chrome */
//   surface: "gray" as const,
//   scoreBands: {
//     high: "green",
//     mid: "lime",
//     low: "yellow",
//     poor: "red",
//   } as const,
// };
