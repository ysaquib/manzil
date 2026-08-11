// Deliberately a Select, not a Switch: a toggle reads as "setting on/off",
// while this picks which value (True/False) the criterion matches against.
import { Select } from "@mantine/core";

import type { WidgetProps } from "./types";

export function BoolWidget({ value, onChange, label, comboboxProps, size = "xs" }: WidgetProps) {
  return (
    <Select
      label={label}
      data={[
        { value: "true", label: "True" },
        { value: "false", label: "False" },
      ]}
      value={value === true ? "true" : value === false ? "false" : null}
      onChange={(next) => next && onChange(next === "true")}
      allowDeselect={false}
      size={size}
      comboboxProps={comboboxProps}
    />
  );
}
