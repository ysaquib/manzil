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
import { useEffect, useState, type ReactNode } from "react";

import { sentenceCase } from "../../lib/text";
import { toneFor } from "./statusColors";
import type { VisitEditMode, VisitEntry, VisitItem } from "./types";
import { checkStateOf, nextCheckState, type CheckState } from "./entries";
import classes from "./VisitControls.module.css";

export interface ControlProps {
  item: VisitItem;
  entry: VisitEntry | undefined;
  /**
   * The control cannot be used *yet* — a unit-scoped item with no unit picked.
   * Greying it out is the message: there is nothing to record here.
   */
  disabled?: boolean;
  /**
   * What kind of surface this is (VC-12).
   *
   * `live`   — an ordinary form.
   * `record` — the tour finished. Greying it out would throw the answer's
   *            colour away, so a record keeps its whole appearance and loses
   *            only its interactivity: a green tick still reads as a pass.
   * `void`   — the tour was **cancelled**. Nothing here was recorded and
   *            nothing ever will be, so unlike a record this genuinely greys
   *            out. The distinction matters: a record is worth reading and a
   *            cancelled form is not, and rendering them identically told you
   *            the opposite.
   */
  mode?: VisitEditMode;
  onSave: (patch: { value?: unknown; answer_text?: string | null }) => void;
}

/** A finished or cancelled tour refuses writes; only `live` accepts them. */
export function isEditable(mode: VisitEditMode | undefined): boolean {
  return (mode ?? "live") === "live";
}

/**
 * Makes its children non-interactive without touching how they look. `inert`
 * (React 19) is what `disabled` should have been for a record: no clicks, no
 * focus, no tab stop, no restyling. Used for the button/chip/rating controls;
 * text controls use the native `readOnly` instead, so the answer stays
 * selectable and copyable.
 */
function Inert({ on, children }: { on: boolean; children: ReactNode }) {
  if (!on) return <>{children}</>;
  return (
    <Box inert className={classes.inert}>
      {children}
    </Box>
  );
}

/** What a record says where an answer would have been. */
function NotRecorded({ label = "Not recorded" }: { label?: string }) {
  return (
    <Text size="xs" c="dimmed" fs="italic">
      {label}
    </Text>
  );
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

export function CheckControl({ item, entry, disabled, mode, onSave }: ControlProps) {
  const readOnly = !isEditable(mode);
  const voided = mode === "void";
  const state = checkStateOf(entry);
  const set = (clicked: Exclude<CheckState, null>) =>
    onSave({ value: nextCheckState(state, clicked) });

  // On a finished tour only the side somebody actually pressed survives: an
  // empty outline beside every answer is an affordance that does nothing.
  //
  // A **cancelled** tour is the opposite case and keeps both sides, greyed. The
  // tour did not happen, so there is no answer to preserve — what the reader
  // needs to see is a form that will never be filled in, which is exactly what
  // a disabled control looks like. Hiding them here would make a cancelled
  // visit indistinguishable from a completed one where nobody checked anything.
  const shows = (side: Exclude<CheckState, null>) =>
    mode === "record" ? state === side : true;

  return (
    <Inert on={Boolean(readOnly)}>
      <Group gap={4} wrap="nowrap" className={classes.tri}>
        {mode === "record" && state === null && <NotRecorded label="Not checked" />}
        {shows("ok") && (
          <Button
            variant={state === "ok" ? toneFor("pass").variant : "default"}
            color={toneFor("pass").color}
            disabled={disabled || voided}
            onClick={() => set("ok")}
            aria-pressed={state === "ok"}
            aria-label={`${item.label}: fine`}
            className={classes.triButton}
          >
            <IconCheck size={17} />
          </Button>
        )}
        {shows("problem") && (
          <Button
            variant={state === "problem" ? toneFor("problem").variant : "default"}
            color={toneFor("problem").color}
            disabled={disabled || voided}
            onClick={() => set("problem")}
            aria-pressed={state === "problem"}
            aria-label={`${item.label}: problem`}
            className={classes.triButton}
          >
            <IconFlag size={17} />
          </Button>
        )}
      </Group>
    </Inert>
  );
}

// ---------------------------------------------------------------------------
// Fact — shape comes from the item's value_schema
// ---------------------------------------------------------------------------

/** Text commits on blur so a save doesn't fire per keystroke. */
function TextValue({
  item,
  entry,
  disabled,
  mode,
  onSave,
  multiline,
}: ControlProps & { multiline?: boolean }) {
  const readOnly = !isEditable(mode);
  const voided = mode === "void";
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
      disabled={disabled || voided}
      readOnly={readOnly}
      aria-label={item.label}
      placeholder={readOnly ? "Not recorded" : "—"}
      autosize={multiline ? true : undefined}
      minRows={multiline ? 2 : undefined}
      onChange={(event) => setDraft(event.currentTarget.value)}
      onBlur={commit}
      w="100%"
    />
  );
}

function NumberValue({ item, entry, disabled, mode, onSave }: ControlProps) {
  const readOnly = !isEditable(mode);
  const voided = mode === "void";
  const stored = typeof entry?.value === "number" ? entry.value : "";
  const [draft, setDraft] = useState<number | string>(stored);
  useEffect(() => setDraft(stored), [stored]);

  const money = schemaType(item) === "money";
  return (
    <NumberInput
      value={draft}
      disabled={disabled || voided}
      readOnly={readOnly}
      hideControls={readOnly}
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

/**
 * The options to draw. A live control offers all of them; a record shows only
 * what was picked, for the same reason the unpressed half of a Check goes.
 */
function optionsToShow(item: VisitItem, chosen: string[], readOnly?: boolean): string[] {
  const all = schemaOptions(item);
  return readOnly ? all.filter((option) => chosen.includes(option)) : all;
}

function EnumValue({ item, entry, disabled, mode, onSave }: ControlProps) {
  const readOnly = !isEditable(mode);
  const voided = mode === "void";
  const stored = typeof entry?.value === "string" ? entry.value : null;
  const shown = optionsToShow(item, stored ? [stored] : [], readOnly);
  if (readOnly && shown.length === 0) return <NotRecorded />;
  return (
    <Inert on={Boolean(readOnly)}>
      <Chip.Group
        value={stored}
        onChange={(value) => onSave({ value: value === stored ? null : value })}
      >
        <Group gap={6} wrap="wrap">
          {shown.map((option) => (
            <Chip
              key={option}
              value={option}
              size="sm"
              disabled={disabled || voided}
              variant={readOnly ? "light" : "outline"}
            >
              {sentenceCase(option)}
            </Chip>
          ))}
        </Group>
      </Chip.Group>
    </Inert>
  );
}

function MultiValue({ item, entry, disabled, mode, onSave }: ControlProps) {
  const readOnly = !isEditable(mode);
  const voided = mode === "void";
  const stored = Array.isArray(entry?.value) ? (entry.value as string[]) : [];
  const shown = optionsToShow(item, stored, readOnly);
  if (readOnly && shown.length === 0) return <NotRecorded />;
  return (
    <Inert on={Boolean(readOnly)}>
      <Chip.Group
        multiple
        value={stored}
        onChange={(value) => onSave({ value: value.length ? value : null })}
      >
        <Group gap={6} wrap="wrap">
          {shown.map((option) => (
            <Chip
              key={option}
              value={option}
              size="sm"
              disabled={disabled || voided}
              variant={readOnly ? "light" : "outline"}
            >
              {sentenceCase(option)}
            </Chip>
          ))}
        </Group>
      </Chip.Group>
    </Inert>
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

export function QuestionControl({ item, entry, disabled, mode, onSave }: ControlProps) {
  const readOnly = !isEditable(mode);
  const voided = mode === "void";
  const stored = entry?.answer_text ?? "";
  const [draft, setDraft] = useState(stored);
  useEffect(() => setDraft(stored), [stored]);
  const asked = Boolean(stored.trim());
  const ready = Boolean(draft.trim()) && draft.trim() !== stored;

  return (
    <Box w="100%">
      <Textarea
        value={draft}
        disabled={disabled || voided}
        readOnly={readOnly}
        aria-label={`Answer: ${item.label}`}
        placeholder={readOnly ? "Never asked" : "Type what they said…"}
        autosize
        minRows={2}
        onChange={(event) => setDraft(event.currentTarget.value)}
      />
      <Group gap="xs" mt={6}>
        {/* On a record the save button goes rather than greys: there is nothing
            here to be persuaded to press. */}
        {!readOnly && (
          <Button
            size="compact-sm"
            // The gate, and the whole point: an answer is what marks a question
            // asked, so there is no way to tick it off without one.
            disabled={disabled || !ready}
            onClick={() => onSave({ answer_text: draft.trim() })}
          >
            {asked ? "Update answer" : "Mark asked"}
          </Button>
        )}
        {asked ? (
          <Badge
            color={toneFor("pass").color}
            variant={toneFor("pass").variant}
            size="sm"
            leftSection={<IconCheck size={11} />}
          >
            Asked
          </Badge>
        ) : readOnly ? (
          <NotRecorded label="Not asked" />
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
  const { item, entry, disabled, mode, onSave } = props;
  const readOnly = !isEditable(mode);
  const voided = mode === "void";
  const type = schemaType(item);

  if (type === "rating") {
    const stored = typeof entry?.value === "number" ? entry.value : 0;
    if (readOnly && stored === 0) return <NotRecorded label="Not rated" />;
    return (
      <Rating
        value={stored}
        readOnly={disabled || readOnly}
        aria-label={item.label}
        onChange={(value) => onSave({ value: value === stored ? null : value })}
      />
    );
  }
  if (type === "boolean") {
    const flagged = entry?.value === true;
    // An unflagged item on a finished tour is one nobody objected to; a dead
    // "Flag it" button says the opposite.
    if (readOnly && !flagged) return <NotRecorded label="Not flagged" />;
    return (
      <Inert on={Boolean(readOnly)}>
        <Button
          size="compact-sm"
          variant={flagged ? toneFor("problem").variant : "default"}
          color={toneFor("problem").color}
          disabled={disabled || voided}
          aria-pressed={flagged}
          aria-label={item.label}
          onClick={() => onSave({ value: flagged ? null : true })}
        >
          {flagged ? "Flagged" : "Flag it"}
        </Button>
      </Inert>
    );
  }
  if (type === "enum") return <EnumValue {...props} />;
  return <TextValue {...props} multiline />;
}

export function ControlForItem(input: ControlProps) {
  // `inert` is presentation, and presentation is not a permission: a record
  // also refuses to save. (The API refuses too — this stops the optimistic
  // write from ever being created.)
  const props: ControlProps = isEditable(input.mode) ? input : { ...input, onSave: () => {} };
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
