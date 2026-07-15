import { MantineColorsTuple } from "@mantine/core";

export const dusk: MantineColorsTuple = [
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
  ]
  // Clay — the supporting warm accent. Reserved for "waiting on the user"
  // (checkpoints); deliberately more amber than red so it never reads as
  // danger.
export const old_clay: MantineColorsTuple = [
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
]
// Warm stone replaces Mantine's cool gray: borders, dimmed text, striped
// rows, and secondary chrome all warm up through this one scale.
export const gray: MantineColorsTuple = [
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
]
// Warm charcoal replaces Mantine's blue-black dark scale. Same role
// indices as stock (6 = surfaces, 7 = body, 4 = borders, 0 = text).
export const dark: MantineColorsTuple = [
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
]
// Status hues re-tuned earthy, same names so `semantic` and component
// code stay untouched: green→moss, lime→olive, yellow→ochre, red stays
// alarming but loses the neon edge.
export const green: MantineColorsTuple = [
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
]
export const lime: MantineColorsTuple = [
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
]
export const yellow: MantineColorsTuple = [
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
]
export const red: MantineColorsTuple = [
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
]

/**
 * Dusky / Clay Design System
 *
 * Philosophy
 * ----------
 * Light Mode:
 *   Warm, earthy, organic, paper-inspired.
 *
 * Dark Mode:
 *   Neutral graphite/slate with a subtle warm bias.
 *
 * Semantic colors remain the same across both themes.
 * Only the neutral environment changes.
 */

// Named Colors ————————————————————————————————————————————————————————————————

// -----------------------------------------------------------------------------
// Warm Stone
// Replaces: Mantine Gray
// Used for: Light mode backgrounds, surfaces, borders, dividers, and text.
// -----------------------------------------------------------------------------

const warm_stone: MantineColorsTuple = [
  "#F8F7F6",
  "#F0EEEC",
  "#E1DDD8",
  "#CBC5BF",
  "#AEA69F",
  "#90877F",
  "#756D66",
  "#5D5650",
  "#45403B",
  "#2E2A27",
];

// -----------------------------------------------------------------------------
// Dark Dusky
// Replaces: Mantine Dark
// Used for: Dark mode backgrounds, surfaces, borders, and elevated UI.
// -----------------------------------------------------------------------------

const dark_dusky: MantineColorsTuple = [
  // "#D5D2CF",
  // "#C2BEB9",
  // "#ADA7A2",
  // "#97908A",
  // "#7F7771",
  // "#68615C",
  // "#534D49",
  // "#413C39",
  // "#312D2B",
  // "#221F1D",
  "#cfc2c5",
  "#b3abaf",
  "#877d80",
  "#6c6164",
  "#423b3d",
  "#3b3336",
  "#2e272a",
  "#272123",
  "#201c1e",
  "#151314",
];

// -----------------------------------------------------------------------------
// Clay
// Replaces: Custom Primary / Brown
// Used for: Brand color, primary buttons, links, emphasis, and brand identity.
// -----------------------------------------------------------------------------

const dusky: MantineColorsTuple = [
  "#f2eef5",
  "#ebdfee",
  "#dfc6e5",
  "#cba6d4",
  "#ba88c6",
  "#ac72b7",
  "#9b5aa9",
  "#8f509b",
  "#7c428a",
  "#6b3977",
];

// -----------------------------------------------------------------------------
// Dusty Brick
// Replaces: Mantine Red
// Used for: Errors, destructive actions, danger states, and validation.
// -----------------------------------------------------------------------------

const dusty_brick: MantineColorsTuple = [
  "#f7eeef",
  "#f3dddd",
  "#edc5c7",
  "#e1a2a3",
  "#d58588",
  "#ca6d6d",
  "#bb595c",
  "#ad4d4d",
  "#9a4144",
  "#85383a",
];

// -----------------------------------------------------------------------------
// Burnt Clay
// Replaces: Mantine Orange
// Used for: Warnings, caution, and attention-grabbing UI.
// -----------------------------------------------------------------------------

const burnt_clay: MantineColorsTuple = [
  "#f6eeee",
  "#f2e2de",
  "#ecccc6",
  "#e0afa4",
  "#d39488",
  "#c78270",
  "#b76c5c",
  "#a86352",
  "#975244",
  "#82473b",
];

// -----------------------------------------------------------------------------
// Muted Ochre
// Replaces: Mantine Yellow
// Used for: Pending states, notifications, informational warnings.
// -----------------------------------------------------------------------------

const muted_ochre: MantineColorsTuple = [
  "#f7f3ed",
  "#f2eedc",
  "#ede2c2",
  "#e3d49f",
  "#d9c582",
  "#ccb86a",
  "#bfa854",
  "#b09b48",
  "#9e873c",
  "#8a7634",
];

// -----------------------------------------------------------------------------
// Olive
// Replaces: Mantine Lime
// Used for: Nature-inspired accents, secondary success, and environmental indicators.
// -----------------------------------------------------------------------------

const olive: MantineColorsTuple = [
  "#f7f6ed",
  "#f0f2dc",
  "#ecedc2",
  "#e0e39f",
  "#d6d982",
  "#c5cc6a",
  "#babf54",
  "#a9b048",
  "#9b9e3c",
  "#878a34",
];

// -----------------------------------------------------------------------------
// Sage
// Replaces: Mantine Green
// Used for: Success, completed actions, healthy states, and confirmations.
// -----------------------------------------------------------------------------

const sage: MantineColorsTuple = [
  "#f0f7ed",
  "#e0f2df",
  "#caedc5",
  "#a8e0a2",
  "#8dd685",
  "#75c96f",
  "#5fbd57",
  "#53ad4c",
  "#489c3e",
  "#3e8736",
];

// -----------------------------------------------------------------------------
// Weathered Teal
// Replaces: Mantine Teal
// Used for: Secondary success, productivity, analytics, and accents.
// -----------------------------------------------------------------------------

const weathered_teal: MantineColorsTuple = [
  "#edf7f1",
  "#dff2ea",
  "#c5edda",
  "#a2e0c3",
  "#85d6b0",
  "#6fc9a2",
  "#57bd8f",
  "#4cad83",
  "#3e9c70",
  "#368761",
];

// -----------------------------------------------------------------------------
// Fog Blue
// Replaces: Mantine Cyan
// Used for: Informational highlights, subtle accents, and secondary information.
// -----------------------------------------------------------------------------

const fog_blue: MantineColorsTuple = [
  "#edf7f5",
  "#dff2f2",
  "#c5edea",
  "#a2e0dc",
  "#85d6d1",
  "#6fc9c6",
  "#57bdb8",
  "#4cadaa",
  "#3e9c95",
  "#368782",
];

// -----------------------------------------------------------------------------
// Slate Blue
// Replaces: Mantine Blue
// Used for: Links, navigation, primary information, and interactive elements.
// -----------------------------------------------------------------------------

const slate_blue: MantineColorsTuple = [
  "#edf6f7",
  "#dfebf2",
  "#c5e2ed",
  "#a2cee0",
  "#85bed6",
  "#6fabc9",
  "#579cbd",
  "#4c8dad",
  "#3e809c",
  "#366f87",
];

// -----------------------------------------------------------------------------
// Storm
// Replaces: Mantine Indigo
// Used for: Navigation, secondary brand accents, and deep informational UI.
// -----------------------------------------------------------------------------

const storm: MantineColorsTuple = [
  "#edf2f7",
  "#dfe3f2",
  "#c5d2ed",
  "#a2b5e0",
  "#859dd6",
  "#6f87c9",
  "#5774bd",
  "#4c66ad",
  "#3e5a9c",
  "#364e87",
];

// -----------------------------------------------------------------------------
// Dusty Lavender
// Replaces: Mantine Violet
// Used for: Creative accents, premium features, and tertiary emphasis.
// -----------------------------------------------------------------------------

const dusty_lavender: MantineColorsTuple = [
  "#edf0f7",
  "#e0dff2",
  "#c5c7ed",
  "#a2a4e0",
  "#8588d6",
  "#6f6fc9",
  "#5759bd",
  "#4c4cad",
  "#3e419c",
  "#363987",
];

// -----------------------------------------------------------------------------
// Muted Plum
// Replaces: Mantine Grape
// Used for: Premium, enterprise, advanced features, and decorative accents.
// -----------------------------------------------------------------------------

const muted_plum: MantineColorsTuple = [
  "#f7f0f8",
  "#f2dff1",
  "#eac6e9",
  "#dea5db",
  "#d289cf",
  "#c572c0",
  "#b661b3",
  "#a654a1",
  "#944890",
  "#803f7d",
];

// -----------------------------------------------------------------------------
// Dusty Rose
// Replaces: Mantine Pink
// Used for: Friendly accents, favorites, decorative UI, and soft highlights.
// -----------------------------------------------------------------------------

const dusty_rose: MantineColorsTuple = [
  "#f7edf6",
  "#f2dfea",
  "#edc5df",
  "#e0a2c9",
  "#d685b8",
  "#c96fa5",
  "#bd5796",
  "#ad4c87",
  "#9c3e79",
  "#873669",
];


export const colors = {
  // Mantine-compatible palette names
  gray: warm_stone,
  dark: dark_dusky,

  red: dusty_brick,
  orange: burnt_clay,
  yellow: muted_ochre,
  green: sage,
  teal: weathered_teal,
  cyan: fog_blue,
  blue: slate_blue,
  indigo: storm,
  violet: dusty_lavender,
  grape: muted_plum,
  pink: dusty_rose,
  lime: olive,

  // Brand palette
  dusky,
  // Descriptive aliases (optional but convenient)
  warm_stone,
  dark_dusky,
  dusty_brick,
  burnt_clay,
  muted_ochre,
  sage,
  weathered_teal,
  fog_blue,
  slate_blue,
  storm,
  dusty_lavender,
  muted_plum,
  dusty_rose,
  olive,
};

