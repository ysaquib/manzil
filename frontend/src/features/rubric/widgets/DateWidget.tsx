import { DateInput } from "@mantine/dates";

import type { WidgetProps } from "./types";

export function DateWidget({ value, onChange, label, placeholder, size }: WidgetProps) {
  return (
    <DateInput
      aria-label={label ?? "date"}
      value={typeof value === "string" ? value : null}
      onChange={(next) => onChange(next)}
      placeholder={placeholder ?? "Choose date"}
      valueFormat="MMM D, YYYY"
      clearable
      size={size}
      popoverProps={{ withinPortal: true }}
    />
  );
}
