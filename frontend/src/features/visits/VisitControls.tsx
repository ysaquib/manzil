// The four entry-kind controls (VC-3, DESIGN §9.7).
//
// One control per kind, because the kinds differ in what they *mean*, not just
// how they look: a Check is a physical test somebody performed (untested is not
// "false"), a Question is asked only once its answer is typed, an Impression is
// one member's opinion, and a Fact is a shared value.
import {
  Badge,
  Box,
  Button,
  Chip,
  Group,
  NumberInput,
  Rating,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { IconCheck, IconFlag } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import { sentenceCase } from "../../lib/text";
import type { VisitEntry, VisitItem } from "./types";
import { checkStateOf, nextCheckState, type CheckState } from "./entries";
import classes from "./VisitControls.module.css";

export interface ControlProps {
  item: VisitItem;
  entry: VisitEntry | undefined;
  disabled?: boolean;
  onSave: (patch: { value?: unknown; answer_text?: string | null }) => void;
}

function schemaType(item: VisitItem): string {
  return String((item.value_schema as { type?: string } | null)?.type ?? "text");
}

function schemaOptions(item: VisitItem): string[] {
  const options = (item.value_schema as { options?: unknown })?.options;
  return Array.isArray(options) ? options.map(String) : [];
}

function schemaUnit(item: VisitItem): string | undefined {
  const unit = (item.value_schema as { unit?: unknown })?.unit;
  return typeof unit === "string" ? unit : undefined;
}

// ---------------------------------------------------------------------------
// Check — tri-state
// ---------------------------------------------------------------------------

export function CheckControl({ item, entry, disabled, onSave }: ControlProps) {
  const state = checkStateOf(entry);
  const set = (clicked: Exclude<CheckState, null>) =>
    onSave({ value: nextCheckState(state, clicked) });

  return (
    <Group gap={4} wrap="nowrap" className={classes.tri}>
      <Button
        variant={state === "ok" ? "filled" : "default"}
        color="green"
        disabled={disabled}
        onClick={() => set("ok")}
        aria-pressed={state === "ok"}
        aria-label={`${item.label}: fine`}
        className={classes.triButton}
      >
        <IconCheck size={17} />
      </Button>
      <Button
        variant={state === "problem" ? "filled" : "default"}
        color="red"
        disabled={disabled}
        onClick={() => set("problem")}
        aria-pressed={state === "problem"}
        aria-label={`${item.label}: problem`}
        className={classes.triButton}
      >
        <IconFlag size={17} />
      </Button>
    </Group>
  );
}

// ---------------------------------------------------------------------------
// Fact — shape comes from the item's value_schema
// ---------------------------------------------------------------------------

/** Text commits on blur so a save doesn't fire per keystroke. */
function TextValue({ item, entry, disabled, onSave, multiline }: ControlProps & { multiline?: boolean }) {
  const stored = typeof entry?.value === "string" ? entry.value : "";
  const [draft, setDraft] = useState(stored);
  useEffect(() => setDraft(stored), [stored]);

  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed === stored) return;
    onSave({ value: trimmed || null });
  };

  const Component = multiline ? Textarea : TextInput;
  return (
    <Component
      value={draft}
      disabled={disabled}
      aria-label={item.label}
      placeholder="—"
      autosize={multiline ? true : undefined}
      minRows={multiline ? 2 : undefined}
      onChange={(event) => setDraft(event.currentTarget.value)}
      onBlur={commit}
      w="100%"
    />
  );
}

function NumberValue({ item, entry, disabled, onSave }: ControlProps) {
  const stored = typeof entry?.value === "number" ? entry.value : "";
  const [draft, setDraft] = useState<number | string>(stored);
  useEffect(() => setDraft(stored), [stored]);

  const money = schemaType(item) === "money";
  return (
    <NumberInput
      value={draft}
      disabled={disabled}
      aria-label={item.label}
      prefix={money ? "$" : undefined}
      suffix={schemaUnit(item) ? ` ${schemaUnit(item)}` : undefined}
      min={0}
      allowNegative={false}
      decimalScale={schemaType(item) === "integer" ? 0 : 2}
      onChange={setDraft}
      onBlur={() => {
        const next = draft === "" || draft === null ? null : Number(draft);
        if (next === (typeof entry?.value === "number" ? entry.value : null)) return;
        onSave({ value: next });
      }}
      w={140}
    />
  );
}

function EnumValue({ item, entry, disabled, onSave }: ControlProps) {
  const stored = typeof entry?.value === "string" ? entry.value : null;
  return (
    <Chip.Group
      value={stored}
      onChange={(value) => onSave({ value: value === stored ? null : value })}
    >
      <Group gap={6} wrap="wrap">
        {schemaOptions(item).map((option) => (
          <Chip key={option} value={option} size="sm" disabled={disabled} variant="outline">
            {sentenceCase(option)}
          </Chip>
        ))}
      </Group>
    </Chip.Group>
  );
}

function MultiValue({ item, entry, disabled, onSave }: ControlProps) {
  const stored = Array.isArray(entry?.value) ? (entry.value as string[]) : [];
  return (
    <Chip.Group
      multiple
      value={stored}
      onChange={(value) => onSave({ value: value.length ? value : null })}
    >
      <Group gap={6} wrap="wrap">
        {schemaOptions(item).map((option) => (
          <Chip key={option} value={option} size="sm" disabled={disabled} variant="outline">
            {sentenceCase(option)}
          </Chip>
        ))}
      </Group>
    </Chip.Group>
  );
}

export function FactControl(props: ControlProps) {
  switch (schemaType(props.item)) {
    case "integer":
    case "number":
    case "money":
      return <NumberValue {...props} />;
    case "enum":
      return <EnumValue {...props} />;
    case "multiselect":
      return <MultiValue {...props} />;
    case "boolean":
      return <EnumValue {...props} />;
    default:
      return <TextValue {...props} />;
  }
}

// ---------------------------------------------------------------------------
// Question — the typed answer *is* the checkmark
// ---------------------------------------------------------------------------

export function QuestionControl({ item, entry, disabled, onSave }: ControlProps) {
  const stored = entry?.answer_text ?? "";
  const [draft, setDraft] = useState(stored);
  useEffect(() => setDraft(stored), [stored]);
  const asked = Boolean(stored.trim());
  const ready = Boolean(draft.trim()) && draft.trim() !== stored;

  return (
    <Box w="100%">
      <Textarea
        value={draft}
        disabled={disabled}
        aria-label={`Answer: ${item.label}`}
        placeholder="Type what they said…"
        autosize
        minRows={2}
        onChange={(event) => setDraft(event.currentTarget.value)}
      />
      <Group gap="xs" mt={6}>
        <Button
          size="compact-sm"
          // The gate, and the whole point: an answer is what marks a question
          // asked, so there is no way to tick it off without one.
          disabled={disabled || !ready}
          onClick={() => onSave({ answer_text: draft.trim() })}
        >
          {asked ? "Update answer" : "Mark asked"}
        </Button>
        {asked ? (
          <Badge color="green" variant="light" size="sm" leftSection={<IconCheck size={11} />}>
            Asked
          </Badge>
        ) : (
          <Text size="xs" c="dimmed" fs="italic">
            {draft.trim() ? "Ready — this records you as the asker" : "Needs an answer first"}
          </Text>
        )}
      </Group>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Impression — one member's opinion
// ---------------------------------------------------------------------------

export function ImpressionControl(props: ControlProps) {
  const { item, entry, disabled, onSave } = props;
  const type = schemaType(item);

  if (type === "rating") {
    const stored = typeof entry?.value === "number" ? entry.value : 0;
    return (
      <Rating
        value={stored}
        readOnly={disabled}
        aria-label={item.label}
        onChange={(value) => onSave({ value: value === stored ? null : value })}
      />
    );
  }
  if (type === "boolean") {
    const flagged = entry?.value === true;
    return (
      <Button
        size="compact-sm"
        variant={flagged ? "filled" : "default"}
        color="red"
        disabled={disabled}
        aria-pressed={flagged}
        aria-label={item.label}
        onClick={() => onSave({ value: flagged ? null : true })}
      >
        {flagged ? "Flagged" : "Flag it"}
      </Button>
    );
  }
  if (type === "enum") return <EnumValue {...props} />;
  return <TextValue {...props} multiline />;
}

export function ControlForItem(props: ControlProps) {
  switch (props.item.kind) {
    case "check":
      return <CheckControl {...props} />;
    case "question":
      return <QuestionControl {...props} />;
    case "impression":
      return <ImpressionControl {...props} />;
    default:
      return <FactControl {...props} />;
  }
}
