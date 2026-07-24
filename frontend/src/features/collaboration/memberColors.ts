export const MEMBER_COLOR_TOKENS = [
  "moss", "ochre", "brick", "olive", "stone", "plum",
] as const;

const TOKEN_COLORS: Record<string, string> = {
  moss: "var(--mantine-color-green-6)",
  ochre: "var(--mantine-color-yellow-6)",
  brick: "var(--mantine-color-red-6)",
  olive: "var(--mantine-color-lime-6)",
  stone: "var(--mantine-color-gray-6)",
  plum: "var(--mantine-color-grape-6)",
};

export function memberColor(value: string | null): string {
  if (!value) return "var(--mantine-color-gray-5)";
  return TOKEN_COLORS[value] ?? value;
}

// Star-fill color for a member's rating: their assigned color, or the yellow
// default when they have none. Shared by the interactive Rating and the
// read-only StarRating so both track the member's color.
export function starColorCss(token: string | null): string {
  return token ? memberColor(token) : "var(--mantine-color-yellow-6)";
}
