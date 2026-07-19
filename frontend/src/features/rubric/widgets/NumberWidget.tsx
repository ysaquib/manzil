import { NumberInput } from "@mantine/core";

import type { WidgetProps } from "./types";

export function NumberWidget({
  schema,
  value,
  onChange,
  label,
  placeholder,
  unit,
  hideControls,
}: WidgetProps) {
  return (
    <NumberInput
      label={label}
      placeholder={placeholder}
      min={schema.minimum}
      max={schema.maximum}
      prefix={unit?.prefix}
      suffix={unit?.suffix}
      thousandSeparator
      hideControls={hideControls}
      value={typeof value === "number" ? value : ""}
      onChange={(next) => onChange(typeof next === "number" ? next : null)}
      size="xs"
    />
  );
}
