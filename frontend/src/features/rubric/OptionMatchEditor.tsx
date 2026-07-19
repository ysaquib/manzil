// Match editor for one rubric option (§8.2 pinned shape {op, value}). The op
// choices and the value input are both driven by the criterion's value_schema
// — the same schema the API validates against (§9.2). Renders as a single
// non-wrapping row: op select + value input(s), each flexing inside the
// option grid's match column.
import { Group, MultiSelect, Select, Text } from "@mantine/core";

import { criterionUnit } from "../../lib/criterionUnits";
import type { MatchOp, OptionMatch } from "../../lib/contracts";
import { OP_LABEL_SHORT, OP_LABEL_WORD, opsForSchema } from "./matchLabels";
import { NumberWidget } from "./widgets/NumberWidget";
import type { ValueSchema } from "./widgets/types";
import { WidgetForSchema } from "./widgets/widgetForSchema";

function defaultValueForOp(op: MatchOp, previous: OptionMatch): unknown {
  if (op === "range") return Array.isArray(previous.value) ? previous.value : [null, null];
  if (op === "in") return Array.isArray(previous.value) ? previous.value : [];
  if (Array.isArray(previous.value)) return null;
  return previous.value;
}

const flexCell = { flex: 1, minWidth: 0 } as const;

export function OptionMatchEditor({
  match,
  schema,
  criterionKey,
  onChange,
}: {
  match: OptionMatch;
  schema: ValueSchema;
  criterionKey?: string | null;
  onChange: (match: OptionMatch) => void;
}) {
  const ops = opsForSchema(schema);
  const isEnum = Boolean(schema.enum);
  const range = Array.isArray(match.value) ? (match.value as (number | null)[]) : [null, null];
  const unit = criterionUnit(criterionKey);

  return (
    <Group gap={6} align="center" wrap="nowrap">
      {ops.length > 1 && (
        <Select
          aria-label="match operator"
          data={ops.map((op) => ({
            value: op,
            // Enum ops read as words ("is", "any of"); numeric ops as symbols
            // with a word gloss in the dropdown.
            label: isEnum ? OP_LABEL_WORD[op] : OP_LABEL_SHORT[op],
          }))}
          renderOption={({ option }) =>
            // Symbol ops get a word gloss ("≤  at most"); word ops ("between",
            // "any of") already say what they mean and render once.
            option.label.length <= 2 ? (
              <Group gap={8} wrap="nowrap">
                <Text size="sm" w={20} ta="center" span>
                  {option.label}
                </Text>
                <Text size="xs" c="dimmed" span>
                  {OP_LABEL_WORD[option.value as MatchOp]}
                </Text>
              </Group>
            ) : (
              <Text size="sm" span>
                {option.label}
              </Text>
            )
          }
          value={match.op}
          onChange={(next) =>
            next &&
            onChange({ op: next as MatchOp, value: defaultValueForOp(next as MatchOp, match) })
          }
          allowDeselect={false}
          w={isEnum ? 92 : match.op === "range" ? 88 : 72}
          size="xs"
          comboboxProps={{ width: "max-content", position: "bottom-start" }}
          styles={{ input: { flexShrink: 0 } }}
        />
      )}
      {match.op === "range" ? (
        <>
          <div style={flexCell}>
            <NumberWidget
              schema={schema}
              value={typeof range[0] === "number" ? range[0] : null}
              onChange={(low) => onChange({ ...match, value: [low, range[1]] })}
              placeholder="from"
              unit={unit}
              hideControls
            />
          </div>
          <Text size="xs" c="dimmed" span>
            –
          </Text>
          <div style={flexCell}>
            <NumberWidget
              schema={schema}
              value={typeof range[1] === "number" ? range[1] : null}
              onChange={(high) => onChange({ ...match, value: [range[0], high] })}
              placeholder="to"
              unit={unit}
              hideControls
            />
          </div>
        </>
      ) : match.op === "in" ? (
        <div style={flexCell}>
          <MultiSelect
            aria-label="match values"
            data={(schema.enum ?? []).map((v) => ({
              value: String(v),
              label: String(v).replaceAll("_", " "),
            }))}
            value={Array.isArray(match.value) ? (match.value as string[]) : []}
            onChange={(next) => onChange({ ...match, value: next })}
            size="xs"
          />
        </div>
      ) : (
        <div style={flexCell}>
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
            unit={unit}
            hideControls
          />
        </div>
      )}
    </Group>
  );
}
