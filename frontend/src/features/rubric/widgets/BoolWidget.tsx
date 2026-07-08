import { Switch } from "@mantine/core";

import type { WidgetProps } from "./types";

export function BoolWidget({ value, onChange, label }: WidgetProps) {
  return (
    <Switch
      label={label}
      checked={value === true}
      onChange={(e) => onChange(e.currentTarget.checked)}
    />
  );
}
