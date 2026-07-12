import { Button, Group, Modal, Stack, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../../auth/useAuth";
import { useHunt } from "../hunts/api";
import { useRubric } from "./api";

export function hasEnabledCriterion(
  saved: { enabled: boolean }[] | undefined,
): boolean {
  return Boolean(saved?.some((criterion) => criterion.enabled));
}

export function CreateRubricPrompt({ huntId }: { huntId: string }) {
  const { session, loading: authLoading } = useAuth();
  const { data: hunt, isLoading: huntLoading } = useHunt(huntId);
  const { data: saved, isLoading: rubricLoading } = useRubric(huntId);
  const location = useLocation();
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    setDismissed(false);
  }, [huntId]);

  const currentUserId = session?.user.id ?? "";
  const isOwner = Boolean(hunt && currentUserId && hunt.owner_id === currentUserId);
  const onRubricRoute =
    location.pathname === `/h/${huntId}/rubric` ||
    location.pathname.startsWith(`/h/${huntId}/rubric/`);
  const empty = saved !== undefined && !hasEnabledCriterion(saved);
  const loading = authLoading || huntLoading || rubricLoading;

  const opened =
    !loading && isOwner && empty && !onRubricRoute && !dismissed;

  return (
    <Modal
      opened={opened}
      onClose={() => setDismissed(true)}
      title="Create a rubric?"
      transitionProps={{ duration: 0 }}
      closeOnClickOutside={false}
    >
      <Stack gap="md">
        <Text size="sm">
          This hunt has no criteria selected yet, so listings cannot be scored.
          Set up a rubric now, or cancel and browse freely.
        </Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setDismissed(true)}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              setDismissed(true);
              void navigate(`/h/${huntId}/rubric`);
            }}
          >
            Create Rubric
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
