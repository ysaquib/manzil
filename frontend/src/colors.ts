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
  "#D5D2CF",
  "#C2BEB9",
  "#ADA7A2",
  "#97908A",
  "#7F7771",
  "#68615C",
  "#534D49",
  "#413C39",
  "#312D2B",
  "#221F1D",
];

// -----------------------------------------------------------------------------
// Clay
// Replaces: Custom Primary / Brown
// Used for: Brand color, primary buttons, links, emphasis, and brand identity.
// -----------------------------------------------------------------------------

const clay: MantineColorsTuple = [
  "#F7F4F1",
  "#EEE7E1",
  "#DED1C7",
  "#C9B6A7",
  "#B19986",
  "#977B68",
  "#7E6555",
  "#655144",
  "#493B32",
  "#2F2520",
];

// -----------------------------------------------------------------------------
// Dusty Brick
// Replaces: Mantine Red
// Used for: Errors, destructive actions, danger states, and validation.
// -----------------------------------------------------------------------------

const dusty_brick: MantineColorsTuple = [
  "#FBF4F2",
  "#F5E4DF",
  "#EBC8BD",
  "#DFA392",
  "#D07C69",
  "#BC5D48",
  "#9D4837",
  "#7C382D",
  "#592822",
  "#381814",
];

// -----------------------------------------------------------------------------
// Burnt Clay
// Replaces: Mantine Orange
// Used for: Warnings, caution, and attention-grabbing UI.
// -----------------------------------------------------------------------------

const burnt_clay: MantineColorsTuple = [
  "#FCF6F1",
  "#F8E8DB",
  "#F0D0B3",
  "#E5B17F",
  "#D79154",
  "#C97633",
  "#A96027",
  "#854C20",
  "#613719",
  "#3F2411",
];

// -----------------------------------------------------------------------------
// Muted Ochre
// Replaces: Mantine Yellow
// Used for: Pending states, notifications, informational warnings.
// -----------------------------------------------------------------------------

const muted_ochre: MantineColorsTuple = [
  "#FCFAF2",
  "#F6F0DD",
  "#ECDDAD",
  "#DFC778",
  "#D0AF4D",
  "#BD9632",
  "#9D7927",
  "#7B5F20",
  "#594418",
  "#392B10",
];

// -----------------------------------------------------------------------------
// Sage
// Replaces: Mantine Green
// Used for: Success, completed actions, healthy states, and confirmations.
// -----------------------------------------------------------------------------

const sage: MantineColorsTuple = [
  "#F3F7F2",
  "#E6EEE3",
  "#CDDEC8",
  "#A9C4A2",
  "#83AA7D",
  "#648F5F",
  "#50744A",
  "#405C3C",
  "#30452D",
  "#202E1F",
];

// -----------------------------------------------------------------------------
// Weathered Teal
// Replaces: Mantine Teal
// Used for: Secondary success, productivity, analytics, and accents.
// -----------------------------------------------------------------------------

const weathered_teal: MantineColorsTuple = [
  "#F2F7F6",
  "#E2ECEA",
  "#C4DBD5",
  "#9EC2B8",
  "#77A79A",
  "#5B8C7E",
  "#487166",
  "#395A51",
  "#2A433D",
  "#1B2C28",
];

// -----------------------------------------------------------------------------
// Fog Blue
// Replaces: Mantine Cyan
// Used for: Informational highlights, subtle accents, and secondary information.
// -----------------------------------------------------------------------------

const fog_blue: MantineColorsTuple = [
  "#F2F8F8",
  "#E2F0F1",
  "#C3DFE3",
  "#99C7CE",
  "#71ADB8",
  "#5692A0",
  "#437783",
  "#355F68",
  "#27464D",
  "#192E33",
];

// -----------------------------------------------------------------------------
// Slate Blue
// Replaces: Mantine Blue
// Used for: Links, navigation, primary information, and interactive elements.
// -----------------------------------------------------------------------------

const slate_blue: MantineColorsTuple = [
  "#F3F6FA",
  "#E5ECF4",
  "#CAD8E8",
  "#A4BAD5",
  "#7D9CC1",
  "#5E7FAE",
  "#4A668E",
  "#3A516F",
  "#2A3B52",
  "#1A2636",
];

// -----------------------------------------------------------------------------
// Storm
// Replaces: Mantine Indigo
// Used for: Navigation, secondary brand accents, and deep informational UI.
// -----------------------------------------------------------------------------

const storm: MantineColorsTuple = [
  "#F3F4F9",
  "#E5E8F2",
  "#CBD2E4",
  "#A9B4CF",
  "#8695B9",
  "#6978A2",
  "#556185",
  "#434D69",
  "#32394E",
  "#212633",
];

// -----------------------------------------------------------------------------
// Dusty Lavender
// Replaces: Mantine Violet
// Used for: Creative accents, premium features, and tertiary emphasis.
// -----------------------------------------------------------------------------

const dusty_lavender: MantineColorsTuple = [
  "#F6F3F8",
  "#ECE6F0",
  "#DACEE3",
  "#C0ABD0",
  "#A587BB",
  "#8C68A5",
  "#735286",
  "#5A416A",
  "#43304F",
  "#2C2035",
];

// -----------------------------------------------------------------------------
// Muted Plum
// Replaces: Mantine Grape
// Used for: Premium, enterprise, advanced features, and decorative accents.
// -----------------------------------------------------------------------------

const muted_plum: MantineColorsTuple = [
  "#F7F3F6",
  "#EFE5EB",
  "#DFC9D7",
  "#C9A6BC",
  "#AF829E",
  "#956584",
  "#7A506B",
  "#614053",
  "#482F3D",
  "#301F28",
];

// -----------------------------------------------------------------------------
// Dusty Rose
// Replaces: Mantine Pink
// Used for: Friendly accents, favorites, decorative UI, and soft highlights.
// -----------------------------------------------------------------------------

const dusty_rose: MantineColorsTuple = [
  "#FBF3F5",
  "#F6E5E9",
  "#EEC8D0",
  "#E09FAE",
  "#D07389",
  "#BC5670",
  "#9B445A",
  "#793547",
  "#572634",
  "#381822",
];

// -----------------------------------------------------------------------------
// Olive
// Replaces: Mantine Lime
// Used for: Nature-inspired accents, secondary success, and environmental indicators.
// -----------------------------------------------------------------------------

const olive: MantineColorsTuple = [
  "#F7F8F2",
  "#EDF0E1",
  "#DCE2C0",
  "#C2CD95",
  "#A5B56E",
  "#889C50",
  "#6D7E3F",
  "#566332",
  "#3F4925",
  "#293018",
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
  clay,
  brown: clay,

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

