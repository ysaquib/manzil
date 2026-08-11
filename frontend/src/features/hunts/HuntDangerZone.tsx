// The Hunt settings danger zone (P3-16's Hunt tab; leave-hunt added per DESIGN
// §20 v3.76).
//
// Three actions that all end someone's relationship with the Hunt, and the
// rules between them are what make this its own component rather than more of
// `HuntSettingsPage`:
//
//   · **Archive** is the Owner's — it hides the Hunt from every member's
//     switcher, so it is not a decision one member makes for the rest.
//   · **Transfer ownership** is the Owner's, and is the precondition for the
//     Owner ever leaving.
//   · **Leave** is everyone else's, and is refused for the Owner (transfer
//     first) and for a lone member (archive instead — a Hunt with nobody in it
//     is readable by no one, including the person who just left).
//
// Every rule here is restated by the API and by RLS
// (`hunt_members_self_leave_delete`). What the frontend adds is telling you
// *which* rule you are up against before you click, instead of after.
import { Button, Group, Modal, Select, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { SectionCard } from "../../components/SectionCard";
import { ApiError } from "../../lib/apiClient";
import { useLeaveHunt, useTransferOwnership, type HuntMember } from "../collaboration/api";
import { usePatchHunt, type Hunt } from "./api";

function notifyError(title: string) {
  return (error: unknown) =>
    notifications.show({
      title,
      message: error instanceof ApiError ? error.message : "Unexpected error",
      color: "red",
    });
}

export function HuntDangerZone({
  hunt,
  members,
  currentUserId,
  isOwner,
  isGhost,
}: {
  hunt: Hunt;
  members: HuntMember[];
  currentUserId: string;
  isOwner: boolean;
  isGhost: boolean;
}) {
  const navigate = useNavigate();
  const patchHunt = usePatchHunt(hunt.id);
  const transferOwnership = useTransferOwnership(hunt.id, isGhost);
  const leaveHunt = useLeaveHunt(hunt.id);

  const [confirmArchive, setConfirmArchive] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [transferTarget, setTransferTarget] = useState<string | null>(null);
  const [confirmTransfer, setConfirmTransfer] = useState(false);

  const transferOptions = members
    .filter((member) => member.user_id !== currentUserId && member.role !== "owner")
    .map((member) => ({ value: member.user_id, label: member.display_name ?? "Member" }));
  const transferTargetName =
    members.find((member) => member.user_id === transferTarget)?.display_name ?? "this Member";

  // The *membership* role, not the `isOwner` prop — that one is also true for a
  // Site Admin in Ghost View, who has no membership at all.
  const selfRole = members.find((member) => member.user_id === currentUserId)?.role;
  const soleMember = members.length === 1;
  const leaveBlockedReason = soleMember
    ? "You're the only member of this hunt, so there is nobody to leave it to. Archive it instead."
    : selfRole === "owner"
      ? "Transfer ownership to another member before you can leave."
      : selfRole === undefined
        ? "Checking your membership…"
        : null;

  const archive = () =>
    patchHunt.mutate(
      { archived: true },
      {
        onSuccess: () => navigate("/"),
        onError: notifyError("Couldn't archive hunt"),
      },
    );

  const transfer = () => {
    if (!transferTarget) return;
    transferOwnership.mutate(transferTarget, {
      onSuccess: () => {
        setConfirmTransfer(false);
        setTransferTarget(null);
        notifications.show({ message: "Ownership transferred", color: "green" });
      },
      onError: notifyError("Couldn't transfer ownership"),
    });
  };

  const leave = () =>
    leaveHunt.mutate(undefined, {
      onSuccess: () => {
        setConfirmLeave(false);
        notifications.show({ message: `You left ${hunt.name}`, color: "green" });
        navigate("/");
      },
      onError: notifyError("Couldn't leave hunt"),
    });

  return (
    <SectionCard title="Danger zone">
      <Stack gap="sm">
        {isOwner && (
          <Stack gap="xs">
            <Text size="xs" c="dimmed">
              Hand this hunt to another Member. You become a Curator; they take over as Owner.
            </Text>
            <Group align="flex-end" gap="sm">
              <Select
                label="Transfer ownership to"
                placeholder={transferOptions.length ? "Choose a Member" : "No other Members yet"}
                data={transferOptions}
                value={transferTarget}
                onChange={setTransferTarget}
                disabled={transferOptions.length === 0}
                style={{ flex: 1 }}
              />
              <Button
                variant="light"
                color="red"
                disabled={!transferTarget}
                onClick={() => setConfirmTransfer(true)}
              >
                Transfer…
              </Button>
            </Group>
          </Stack>
        )}

        <Text size="xs" c="dimmed">
          {isOwner
            ? "Hides this hunt from the switcher; nothing is deleted."
            : "Only the Owner can archive this hunt."}
        </Text>
        <Button
          variant="light"
          color="red"
          disabled={!isOwner}
          onClick={() => setConfirmArchive(true)}
        >
          Archive hunt…
        </Button>

        {/* A ghost has no membership to end, so the control is absent rather
            than disabled — there is no state in which it would become usable. */}
        {!isGhost && (
          <>
            <Text size="xs" c="dimmed">
              {leaveBlockedReason ??
                "You lose access to this hunt. Your comments and ratings stay with it."}
            </Text>
            <Button
              variant="light"
              color="red"
              disabled={leaveBlockedReason !== null}
              onClick={() => setConfirmLeave(true)}
            >
              Leave hunt…
            </Button>
          </>
        )}
      </Stack>

      <Modal opened={confirmArchive} onClose={() => setConfirmArchive(false)} title="Archive hunt?">
        <Stack>
          <Text size="sm">
            <Text span fw={600}>
              {hunt.name}
            </Text>{" "}
            disappears from your hunts. Listings, scores, and history are kept.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmArchive(false)}>
              Cancel
            </Button>
            <Button color="red" onClick={archive} loading={patchHunt.isPending}>
              Archive
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={confirmTransfer}
        onClose={() => setConfirmTransfer(false)}
        title="Transfer ownership?"
      >
        <Stack>
          <Text size="sm">
            <Text span fw={600}>
              {transferTargetName}
            </Text>{" "}
            becomes the Owner of{" "}
            <Text span fw={600}>
              {hunt.name}
            </Text>
            . You become a{" "}
            <Text span fw={600}>
              Curator
            </Text>{" "}
            and lose owner-only controls. This can only be undone by the new Owner.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmTransfer(false)}>
              Cancel
            </Button>
            <Button color="red" onClick={transfer} loading={transferOwnership.isPending}>
              Transfer ownership
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal opened={confirmLeave} onClose={() => setConfirmLeave(false)} title="Leave hunt?">
        <Stack>
          <Text size="sm">
            You lose access to{" "}
            <Text span fw={600}>
              {hunt.name}
            </Text>{" "}
            and everything in it. Your comments and ratings stay for the other members. An Owner can
            invite you back.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmLeave(false)}>
              Cancel
            </Button>
            <Button color="red" onClick={leave} loading={leaveHunt.isPending}>
              Leave hunt
            </Button>
          </Group>
        </Stack>
      </Modal>
    </SectionCard>
  );
}
