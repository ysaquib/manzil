// Confirmation for the two hard-to-reverse visit actions (UI_DESIGN §4:
// destructive actions sit behind a confirm, not a hover).
//
// Its own component rather than two inline Modals because cancel and delete
// differ only in copy and whether a reason is collected — and because a dialog
// with props is directly testable, while a Menu-item click never reaches a
// Modal under jsdom.
import { Button, Group, Modal, Stack, Text, TextInput } from "@mantine/core";
import { useState } from "react";

export function VisitConfirmDialog({
  opened,
  onClose,
  title,
  body,
  confirmLabel,
  cancelLabel = "Keep it",
  loading = false,
  reasonLabel,
  reasonPlaceholder,
  onConfirm,
}: {
  opened: boolean;
  onClose: () => void;
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel?: string;
  loading?: boolean;
  /** When set, an optional free-text reason is collected and passed on. */
  reasonLabel?: string;
  reasonPlaceholder?: string;
  onConfirm: (reason?: string) => void;
}) {
  const [reason, setReason] = useState("");

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={title}
      // Reopening should not show a stale reason from a dialog you backed out of.
      onExitTransitionEnd={() => setReason("")}
    >
      <Stack gap="sm">
        <Text size="sm">{body}</Text>
        {reasonLabel && (
          <TextInput
            label={reasonLabel}
            placeholder={reasonPlaceholder}
            value={reason}
            onChange={(event) => setReason(event.currentTarget.value)}
          />
        )}
        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>
            {cancelLabel}
          </Button>
          <Button
            color="red"
            loading={loading}
            onClick={() => onConfirm(reasonLabel ? reason.trim() || undefined : undefined)}
          >
            {confirmLabel}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
