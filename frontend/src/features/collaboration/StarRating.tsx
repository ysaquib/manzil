import { Rating } from "@mantine/core";

export function StarRating({
  value,
  size = "sm",
  color,
}: {
  value: number;
  size?: "sm" | "lg";
  /** Mantine/CSS color for filled stars; omitted → theme yellow. */
  color?: string;
}) {
  const clamped = Math.max(0, Math.min(5, value));
  return (
    <Rating
      value={clamped}
      readOnly
      fractions={2}
      color={color ?? "yellow"}
      size={size}
      aria-label={`${value} of 5`}
    />
  );
}
