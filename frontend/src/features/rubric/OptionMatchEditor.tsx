// Match editor for one rubric option (§8.2 pinned shape {op, value}). The op
// choices and the value input are both driven by the criterion's value_schema
// — the same schema the API validates against (§9.2).
import { Group, MultiSelect, Select } from "@mantine/core";

import type { MatchOp, OptionMatch } from "../../lib/contracts";
import { OP_LABEL_SHORT, opsForSchema } from "./matchLabels";
import { NumberWidget } from "./widgets/NumberWidget";
import type { ValueSchema } from "./widgets/types";
import { WidgetForSchema } from "./widgets/widgetForSchema";

function defaultValueForOp(op: MatchOp, previous: OptionMatch): unknown {
  if (op === "range") return Array.isArray(previous.value) ? previous.value : [null, null];
  if (op === "in") return Array.isArray(previous.value) ? previous.value : [];
  if (Array.isArray(previous.value)) return null;
  return previous.value;
}

export function OptionMatchEditor({
  match,
  schema,
  onChange,
}: {
  match: OptionMatch;
  schema: ValueSchema;
  onChange: (match: OptionMatch) => void;
}) {
  const ops = opsForSchema(schema);
  const range = Array.isArray(match.value) ? (match.value as (number | null)[]) : [null, null];

  return (
    <Group gap="xs" align="flex-end" wrap="wrap">
      {ops.length > 1 && (
        <Select
          aria-label="match operator"
          data={ops.map((op) => ({
            value: op,
            label: OP_LABEL_SHORT[op],
          }))}
          value={match.op}
          onChange={(next) =>
            next &&
            onChange({ op: next as MatchOp, value: defaultValueForOp(next as MatchOp, match) })
          }
          allowDeselect={false}
          w={90}
          size="xs"
        />
      )}
      {match.op === "range" ? (
        <>
          <NumberWidget
            schema={schema}
            value={typeof range[0] === "number" ? range[0] : null}
            onChange={(low) => onChange({ ...match, value: [low, range[1]] })}
            placeholder="from"
          />
          <NumberWidget
            schema={schema}
            value={typeof range[1] === "number" ? range[1] : null}
            onChange={(high) => onChange({ ...match, value: [range[0], high] })}
            placeholder="to"
          />
        </>
      ) : match.op === "in" ? (
        <MultiSelect
          aria-label="match values"
          data={(schema.enum ?? []).map((v) => String(v))}
          value={Array.isArray(match.value) ? (match.value as string[]) : []}
          onChange={(next) => onChange({ ...match, value: next })}
          w={220}
          size="xs"
        />
      ) : (
        <WidgetForSchema
          schema={schema}
          value={
            typeof match.value === "number" ||
            typeof match.value === "boolean" ||
            typeof match.value === "string"
              ? match.value
              : null
          }
          onChange={(value) => onChange({ ...match, value })}
        />
      )}
    </Group>
  );
}
