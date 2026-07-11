// Members surface (P2-8, DESIGN §13.1). Every role sees the roster; only the
// owner gets the role Select + Remove controls on other, non-owner rows. Role
// gating here is UX — RLS + the API are the enforcement (frontend/AGENTS.md).
import { Badge, Button, Group, Modal, Select, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { Section } from "../../components/Section";
import { ApiError } from "../../lib/apiClient";
import { semantic } from "../../theme";
import { useRemoveMember, useSetMemberRole, type HuntMember } from "./api";
import { memberColor } from "./memberColors";

const ROLE_LABEL: Record<HuntMember["role"], string> = {
  owner: "Owner",
  curator: "Curator",
  member: "Member",
};

function ColorDot({ color }: { color: string | null }) {
  return (
    <span
      aria-hidden
      style={{
        width: 12,
        height: 12,
        borderRadius: "50%",
        background: memberColor(color),
        display: "inline-block",
        flexShrink: 0,
      }}
    />
  );
}

export function MembersSection({
  huntId,
  members,
  currentUserId,
  isOwner,
}: {
  huntId: string;
  members: HuntMember[];
  currentUserId: string;
  isOwner: boolean;
}) {
  const setRole = useSetMemberRole(huntId);
  const removeMember = useRemoveMember(huntId);
  const [pendingRemove, setPendingRemove] = useState<HuntMember | null>(null);

  const removeName = pendingRemove?.display_name ?? "this Member";

  const confirmRemove = () => {
    if (!pendingRemove) return;
    removeMember.mutate(pendingRemove.user_id, {
      onSuccess: () => {
        setPendingRemove(null);
        notifications.show({ message: "Member removed", color: "green" });
      },
      onError: (error) =>
        notifications.show({
          title: "Couldn't remove member",
          message: error instanceof ApiError ? error.message : "Unexpected error",
          color: "red",
        }),
    });
  };

  return (
    <Section title="Members">
      <Stack gap="sm">
        {members.map((member) => {
          const controllable = isOwner && member.role !== "owner" && member.user_id !== currentUserId;
          return (
            <Group key={member.user_id} justify="space-between" wrap="nowrap">
              <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
                <ColorDot color={member.color} />
                <Text size="sm" truncate>
                  {member.display_name ?? "Member"}
                  {member.user_id === currentUserId && (
                    <Text span c="dimmed" size="xs">
                      {" "}
                      (you)
                    </Text>
                  )}
                </Text>
              </Group>
              <Group gap="xs" wrap="nowrap">
                {controllable ? (
                  <Select
                    aria-label={`Role for ${member.display_name ?? "Member"}`}
                    size="xs"
                    w={120}
                    data={[
                      { value: "member", label: "Member" },
                      { value: "curator", label: "Curator" },
                    ]}
                    value={member.role === "curator" ? "curator" : "member"}
                    allowDeselect={false}
                    onChange={(value) =>
                      value &&
                      setRole.mutate(
                        { userId: member.user_id, role: value as "member" | "curator" },
                        {
                          onError: (error) =>
                            notifications.show({
                              title: "Couldn't change role",
                              message: error instanceof ApiError ? error.message : "Unexpected error",
                              color: "red",
                            }),
                        },
                      )
                    }
                  />
                ) : (
                  <Badge variant="light" color={member.role === "owner" ? "dusk" : "gray"}>
                    {ROLE_LABEL[member.role]}
                  </Badge>
                )}
                {controllable && (
                  <Button
                    size="xs"
                    variant="subtle"
                    color={semantic.danger}
                    onClick={() => setPendingRemove(member)}
                  >
                    Remove
                  </Button>
                )}
              </Group>
            </Group>
          );
        })}
      </Stack>

      <Modal
        opened={pendingRemove !== null}
        onClose={() => setPendingRemove(null)}
        title="Remove member?"
      >
        <Stack>
          <Text size="sm">
            <Text span fw={600}>
              {removeName}
            </Text>{" "}
            loses access to this hunt. Their comments and ratings are kept.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setPendingRemove(null)}>
              Cancel
            </Button>
            <Button color={semantic.danger} onClick={confirmRemove} loading={removeMember.isPending}>
              Remove
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Section>
  );
}
