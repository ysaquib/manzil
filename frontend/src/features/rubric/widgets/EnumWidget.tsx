import { Select } from "@mantine/core";

import type { WidgetProps } from "./types";

export function EnumWidget({ schema, value, onChange, label }: WidgetProps) {
  const options = (schema.enum ?? []).map((v) => ({
    value: String(v),
    label: String(v).replaceAll("_", " "),
  }));
  return (
    <Select
      label={label}
      data={options}
      value={value === null || value === undefined ? null : String(value)}
      onChange={(next) => onChange(next)}
      allowDeselect={false}
      size="xs"
    />
  );
}
