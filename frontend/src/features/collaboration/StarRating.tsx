import classes from "./StarRating.module.css";

export function StarRating({ value, size = "sm" }: { value: number; size?: "sm" | "lg" }) {
  const pct = Math.max(0, Math.min(100, (value / 5) * 100));
  return (
    <span className={`${classes.stars} ${classes[size]}`} aria-label={`${value} of 5`}>
      <span className={classes.base}>★★★★★</span>
      <span className={classes.fill} data-fill style={{ width: `${pct}%` }}>
        ★★★★★
      </span>
    </span>
  );
}
