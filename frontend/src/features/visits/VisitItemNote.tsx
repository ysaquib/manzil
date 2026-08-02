// Per-row notes (VC-15).
//
// The template asks 248 questions and had nowhere to put the 249th thought. A
// tri-state cannot say *why* the water pressure failed, and a 2-out-of-5 cannot
// say "the counter run is short — no landing space next to the oven", which is
// the sentence the whole visit turns on when you read it three days later.
//
// This is deliberately not a new table. `visit_entries.note` has existed since
// VC-3 and was simply never surfaced, so a note is an ordinary answer write: it
// inherits append-only history, attribution, the offline queue and conflict
// detection without a line of new plumbing.
import { Box, Button, Text, Textarea } from "@mantine/core";
import { IconMessage2, IconMessage2Off } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import type { VisitEntry, VisitEditMode } from "./types";
import classes from "./VisitItemNote.module.css";

export function VisitItemNote({
  entry,
  label,
  mode,
  onSave,
}: {
  entry: VisitEntry | undefined;
  /** The row's own label — the note's accessible name hangs off it. */
  label: string;
  mode: VisitEditMode;
  onSave: (note: string | null) => void;
}) {
  const stored = entry?.note ?? "";
  const [open, setOpen] = useState(Boolean(stored));
  const [draft, setDraft] = useState(stored);

  useEffect(() => {
    setDraft(stored);
    // A note arriving from a teammate opens the box rather than hiding behind
    // a collapsed "add note" that implies there is nothing there.
    if (stored) setOpen(true);
  }, [stored]);

  const editable = mode === "live";

  // On a record with no note there is nothing to show and nothing to add: an
  // "add note" button that cannot be pressed is worse than no button.
  if (!editable && !stored) return null;

  if (!editable) {
    return (
      <Text size="xs" c="dimmed" className={classes.readNote}>
        {stored}
      </Text>
    );
  }

  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed === stored) return;
    onSave(trimmed || null);
  };

  return (
    <Box>
      <Button
        variant="subtle"
        size="compact-xs"
        className={classes.toggle}
        leftSection={open ? <IconMessage2Off size={12} /> : <IconMessage2 size={12} />}
        onClick={() => {
          if (open && draft.trim()) commit();
          setOpen((previous) => !previous);
        }}
      >
        {open ? "Hide note" : stored ? "Note" : "Add note"}
      </Button>
      {open && (
        <Textarea
          className={classes.box}
          value={draft}
          autosize
          minRows={2}
          aria-label={`Note: ${label}`}
          placeholder="What you'd have said out loud…"
          onChange={(event) => setDraft(event.currentTarget.value)}
          onBlur={commit}
        />
      )}
    </Box>
  );
}
