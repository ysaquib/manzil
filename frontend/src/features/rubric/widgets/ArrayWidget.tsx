import { MultiSelect } from "@mantine/core";

import type { WidgetProps } from "./types";

export function ArrayWidget({ schema, value, onChange, label, comboboxProps }: WidgetProps) {
  const options = (schema.items?.enum ?? []).map((item) => ({
    value: String(item),
    label: String(item).replaceAll("_", " "),
  }));
  return (
    <MultiSelect
      label={label}
      aria-label={label ?? "set values"}
      data={options}
      value={Array.isArray(value) ? value : []}
      onChange={onChange}
      searchable
      clearable
      size="xs"
      comboboxProps={comboboxProps}
    />
  );
}
