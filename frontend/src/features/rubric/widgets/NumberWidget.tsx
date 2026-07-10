import { NumberInput } from "@mantine/core";

import type { WidgetProps } from "./types";

export function NumberWidget({ schema, value, onChange, label, placeholder }: WidgetProps) {
  return (
    <NumberInput
      label={label}
      placeholder={placeholder}
      min={schema.minimum}
      max={schema.maximum}
      value={typeof value === "number" ? value : ""}
      onChange={(next) => onChange(typeof next === "number" ? next : null)}
      size="xs"
    />
  );
}
