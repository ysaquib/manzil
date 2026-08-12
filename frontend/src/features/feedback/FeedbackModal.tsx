// Submit feedback (P3-16, DESIGN §20 v3.27). A modal rather than a route:
// feedback is almost always about the screen you are on, and navigating away to
// write it loses the thing you were describing.
//
// The context strip is the point — route (Drawer params included), hunt, build,
// and account travel with the report, so two lines of prose are still
// actionable. It is shown, not hidden, because a person should be able to see
// what they are sending.
import {
  Button,
  Chip,
  Group,
  Modal,
  Stack,
  Text,
  Textarea,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconInfoCircle } from "@tabler/icons-react";
import { useState } from "react";
import { useLocation, useParams } from "react-router-dom";

import { useAuth } from "../../auth/useAuth";
import { ApiError } from "../../lib/apiClient";
import { feedbackBuildContext, useApiBuildInfo } from "../../lib/buildInfo";
import {
  FEEDBACK_CATEGORIES,
  appVersion,
  useSubmitFeedback,
  type FeedbackCategory,
} from "./api";

const MAX_BODY = 4000;

export function FeedbackModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const location = useLocation();
  const { huntId } = useParams();
  const { session } = useAuth();
  const submit = useSubmitFeedback();
  const apiBuild = useApiBuildInfo();

  const [category, setCategory] = useState<FeedbackCategory>("bug");
  const [body, setBody] = useState("");

  // Captured at render, so the strip shows exactly what will be sent — including
  // the Drawer that is open behind the modal.
  const route = `${location.pathname}${location.search}`;
  const version = feedbackBuildContext(appVersion(), apiBuild.data);

  const close = () => {
    onClose();
    // Reset only after the modal is dismissed; a failed send keeps the text.
    setBody("");
    setCategory("bug");
  };

  const send = () => {
    submit.mutate(
      {
        category,
        body: body.trim(),
        route,
        hunt_id: huntId ?? null,
        app_version: version,
      },
      {
        onSuccess: () => {
          notifications.show({ message: "Feedback sent — thank you", color: "green" });
          close();
        },
        onError: (error) =>
          notifications.show({
            title: "Couldn't send feedback",
            message: error instanceof ApiError ? error.message : "Unexpected error",
            color: "red",
          }),
      },
    );
  };

  return (
    <Modal
      opened={opened}
      onClose={close}
      title="Submit feedback"
      size="md"
      zIndex={1100}
    >
      <Stack gap="md">
        <Stack gap={6}>
          <Text size="sm" fw={600}>
            What kind of feedback?
          </Text>
          <Chip.Group
            multiple={false}
            value={category}
            onChange={(value) => setCategory(value as FeedbackCategory)}
          >
            <Group gap="xs">
              {FEEDBACK_CATEGORIES.map((option) => (
                <Chip key={option.value} value={option.value} variant="outline" size="sm">
                  {option.label}
                </Chip>
              ))}
            </Group>
          </Chip.Group>
        </Stack>

        <Textarea
          label="Tell us what happened"
          description="Steps, what you expected, what you got — whatever you have."
          placeholder="The all-in cost in the drawer doesn't match the Overview table for the same listing…"
          autosize
          minRows={4}
          maxRows={10}
          maxLength={MAX_BODY}
          value={body}
          onChange={(event) => setBody(event.currentTarget.value)}
        />

        <Group
          gap={6}
          wrap="wrap"
          align="center"
          p="sm"
          style={{
            background: "var(--mantine-color-default)",
            border: "1px solid var(--mantine-color-default-border)",
            borderRadius: "var(--mantine-radius-md)",
          }}
        >
          <IconInfoCircle size={14} stroke={1.6} color="var(--mantine-color-dimmed)" />
          <Text size="xs" c="dimmed">
            Sent with:
          </Text>
          <Text size="xs" c="dimmed" ff="monospace" style={{ wordBreak: "break-all" }}>
            {route}
          </Text>
          {version && (
            <Text size="xs" c="dimmed" ff="monospace">
              · {version}
            </Text>
          )}
          {session?.user.email && (
            <Text size="xs" c="dimmed" ff="monospace">
              · {session.user.email}
            </Text>
          )}
        </Group>

        <Group justify="flex-end" gap="xs">
          <Button variant="subtle" color="gray" onClick={close}>
            Cancel
          </Button>
          <Button onClick={send} loading={submit.isPending} disabled={body.trim().length === 0}>
            Send feedback
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
