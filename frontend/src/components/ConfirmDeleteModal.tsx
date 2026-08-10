// One confirmation for every deletion, single or bulk (UI Decision Log 2026-08-10).
//
// The rule it encodes: nothing is deleted without the operator first *seeing the
// subjects by name*. Deleting one thing asks for that thing's own name back —
// which cannot be typed by momentum — and deleting several lists every one of
// them in a scrollable pane and asks for a fixed phrase naming the noun and the
// count. A row that cannot be deleted is shown with its reason rather than
// silently dropped, because "why is nothing happening" is the question a
// filtered-out row always produces.
//
// Reversible removals (a membership, a pending invite) pass
// `requireTypedConfirmation={false}`: they still show what goes, but asking a
// person to type a name to undo something undoable teaches them to type without
// reading, which is exactly what the typing is meant to prevent.
import {
  Alert,
  Button,
  Group,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useEffect, useMemo, useState, type ReactNode } from "react";

export interface DeletionTarget {
  id: string;
  /** Shown in the list and, for a single target, typed back to confirm. */
  label: string;
  /** Quiet second line — an email, a role, a count. */
  description?: string;
  /** Set when this one cannot go: it is listed, dimmed, and skipped. */
  blockedReason?: string;
}

export interface DeletionNoun {
  singular: string;
  plural: string;
}

/** The phrase a bulk deletion asks for, e.g. "permanently delete all selected accounts". */
export function bulkConfirmationPhrase(noun: DeletionNoun): string {
  return `permanently delete all selected ${noun.plural}`;
}

export interface ConfirmDeleteModalProps {
  opened: boolean;
  onClose: () => void;
  targets: DeletionTarget[];
  noun: DeletionNoun;
  /** Defaults to "Permanently delete <n> <noun>?". */
  title?: string;
  /** Consequence copy, shown in the red alert above the list. */
  warning?: ReactNode;
  /** Extra impact detail (counts, blockers) between the list and the input. */
  children?: ReactNode;
  confirmLabel?: string;
  /** False for reversible removals: the list still shows, the typing does not. */
  requireTypedConfirmation?: boolean;
  loading?: boolean;
  /** Receives only the targets that are actually deletable. */
  onConfirm: (targets: DeletionTarget[]) => void;
}

const DEFAULT_WARNING =
  "This cannot be undone. Everything owned by the records below goes with them.";

export function ConfirmDeleteModal({
  opened,
  onClose,
  targets,
  noun,
  title,
  warning,
  children,
  confirmLabel,
  requireTypedConfirmation = true,
  loading = false,
  onConfirm,
}: ConfirmDeleteModalProps) {
  const [typed, setTyped] = useState("");

  const deletable = useMemo(
    () => targets.filter((target) => !target.blockedReason),
    [targets],
  );
  const blocked = targets.length - deletable.length;
  // The phrase is the subject's own name while there is exactly one subject —
  // including a bulk selection whittled down to one by its blockers, since what
  // is about to happen really is a single deletion, and including a lone
  // subject that is itself blocked, so the field does not vanish out from under
  // someone reading why they are being refused.
  const only = deletable.length === 1 ? deletable[0] : targets.length === 1 ? targets[0] : null;
  const single = only !== null;
  const phrase = only ? only.label : bulkConfirmationPhrase(noun);
  // A name is matched exactly; the fixed phrase is matched case-insensitively,
  // because capitalising a sentence you were told to type is not a mistake.
  const matched = single
    ? typed.trim() === phrase
    : typed.trim().toLowerCase() === phrase.toLowerCase();

  // A different selection is a different confirmation: never carry the typed
  // phrase across from the last one.
  const identity = targets.map((target) => target.id).join("|");
  useEffect(() => {
    setTyped("");
  }, [opened, identity]);

  const close = () => {
    if (!loading) onClose();
  };

  const confirmed = deletable.length > 0 && (!requireTypedConfirmation || matched);
  const countLabel = `${deletable.length} ${
    deletable.length === 1 ? noun.singular : noun.plural
  }`;
  const defaultTitle =
    deletable.length === 0
      ? `Nothing selected can be deleted`
      : `Permanently delete ${countLabel}?`;

  return (
    <Modal
      opened={opened}
      onClose={close}
      title={title ?? defaultTitle}
      closeOnClickOutside={!loading}
      closeOnEscape={!loading}
      size={targets.length > 1 ? "lg" : "md"}
    >
      <Stack>
        <Alert color="red" title="This cannot be undone">
          {warning ?? DEFAULT_WARNING}
        </Alert>

        <Stack gap={4}>
          <Text size="xs" fw={600} c="dimmed">
            {targets.length === 1 ? "About to delete" : `About to delete (${targets.length})`}
          </Text>
          <Paper withBorder radius="sm">
            <ScrollArea.Autosize mah={220} type="auto" aria-label={`${noun.plural} to delete`}>
              <Stack gap={0} p="xs">
                {targets.map((target) => (
                  <Stack key={target.id} gap={0} py={4}>
                    <Text size="sm" fw={600} c={target.blockedReason ? "dimmed" : undefined}>
                      {target.label}
                    </Text>
                    {target.description && (
                      <Text size="xs" c="dimmed">
                        {target.description}
                      </Text>
                    )}
                    {target.blockedReason && (
                      <Text size="xs" c="red">
                        Skipped — {target.blockedReason}
                      </Text>
                    )}
                  </Stack>
                ))}
              </Stack>
            </ScrollArea.Autosize>
          </Paper>
        </Stack>

        {blocked > 0 && (
          <Alert color="yellow">
            {blocked} of {targets.length} cannot be deleted and will be skipped.
          </Alert>
        )}

        {children}

        {requireTypedConfirmation && targets.length > 0 && (
          <TextInput
            label={`Type “${phrase}” to confirm`}
            value={typed}
            onChange={(event) => setTyped(event.currentTarget.value)}
            autoComplete="off"
            disabled={loading}
            error={
              typed.length > 0 && !matched
                ? single
                  ? "That name does not match"
                  : "That phrase does not match"
                : undefined
            }
          />
        )}

        <Group justify="flex-end">
          <Button variant="default" onClick={close} disabled={loading}>
            Cancel
          </Button>
          <Button
            color="red"
            loading={loading}
            disabled={!confirmed}
            onClick={() => confirmed && onConfirm(deletable)}
          >
            {confirmLabel ??
              (deletable.length === 0 ? "Permanently delete" : `Permanently delete ${countLabel}`)}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
