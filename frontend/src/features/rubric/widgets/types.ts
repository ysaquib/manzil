// The DESIGN §8.2 `value_schema` shape — the single source of truth the API
// validates rubric options against and the frontend renders widgets from.
export interface ValueSchema {
  type: "integer" | "number" | "boolean" | "string";
  minimum?: number;
  maximum?: number;
  enum?: (string | number)[];
}

export type WidgetValue = number | boolean | string | null;

export interface WidgetProps {
  schema: ValueSchema;
  value: WidgetValue;
  onChange: (value: WidgetValue) => void;
  label?: string;
}
