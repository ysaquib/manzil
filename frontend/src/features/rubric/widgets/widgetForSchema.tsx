// value_schema -> widget dispatcher (Phase 1 plan §5.3, DESIGN §8.2). The same
// schema the API validates rubric options against picks the input here — one
// schema, two consumers.
import type { ComponentType } from "react";

import { BoolWidget } from "./BoolWidget";
import { ArrayWidget } from "./ArrayWidget";
import { EnumWidget } from "./EnumWidget";
import { NumberWidget } from "./NumberWidget";
import { DateWidget } from "./DateWidget";
import type { ValueSchema, WidgetProps } from "./types";

export function selectWidget(schema: ValueSchema): ComponentType<WidgetProps> {
  if (schema.type === "array") return ArrayWidget;
  if (schema.type === "boolean") return BoolWidget;
  if (schema.type === "string" && schema.format === "date") return DateWidget;
  if (schema.type === "string" && schema.enum) return EnumWidget;
  if (schema.type === "integer" || schema.type === "number") return NumberWidget;
  // A string without an enum is free text — Phase 1 rubrics don't use it; fall
  // back to the enum widget's empty state rather than crashing.
  return EnumWidget;
}

export function WidgetForSchema(props: WidgetProps) {
  const Widget = selectWidget(props.schema);
  return <Widget {...props} />;
}
