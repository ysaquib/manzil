// The DESIGN §8.2 `value_schema` shape — the single source of truth the API
// validates rubric options against and the frontend renders widgets from.
import type { UnitFormat } from "../../../lib/criterionUnits";

export interface ValueSchema {
  type: "integer" | "number" | "boolean" | "string" | "array";
  minimum?: number;
  maximum?: number;
  enum?: (string | number)[];
  items?: ValueSchema;
  minItems?: number;
  maxItems?: number;
  uniqueItems?: boolean;
}

export type WidgetValue = number | boolean | string | string[] | null;

export interface WidgetProps {
  schema: ValueSchema;
  value: WidgetValue;
  onChange: (value: WidgetValue) => void;
  label?: string;
  placeholder?: string;
  /** Display unit (e.g. "$", " min") rendered inline with the number. */
  unit?: UnitFormat;
  /** Hide the number spinner in tight layouts (rubric option rows). */
  hideControls?: boolean;
  /** Forwarded to Select/MultiSelect when nested inside another floating layer (e.g. Popover). */
  comboboxProps?: { withinPortal?: boolean };
}
