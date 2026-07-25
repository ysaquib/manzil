import {
  ActionIcon,
  Badge,
  Button,
  Checkbox,
  Group,
  Menu,
  Stack,
  Text,
  Textarea,
} from "@mantine/core";
import { IconDotsVertical, IconPencil, IconTrash } from "@tabler/icons-react";
import dayjs from "dayjs";
import { useState } from "react";

import { useAuth } from "../../auth/useAuth";
import {
  useComments,
  useCreateComment,
  useDeleteComment,
  useUpdateComment,
  type HuntMember,
} from "./api";
import { memberColor } from "./memberColors";

interface CurrentUnitGroup {
  key: string;
  label: string;
}

function unitGroupLabel(key: string): string {
  const [bedsText, bathsText] = key.split("-");
  const beds = Number(bedsText);
  return `${beds === 0 ? "Studio" : `${beds} bd`} / ${bathsText} ba`;
}

export function CommentsSection({
  listingId,
  members,
  currentUnitGroup,
}: {
  listingId: string;
  members: HuntMember[];
  currentUnitGroup: CurrentUnitGroup | null;
}) {
  const { session } = useAuth();
  const [body, setBody] = useState("");
  const [scopeToCurrentGroup, setScopeToCurrentGroup] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editBody, setEditBody] = useState("");
  const { data: comments = [] } = useComments(listingId);
  const create = useCreateComment(listingId);
  const update = useUpdateComment(listingId);
  const remove = useDeleteComment(listingId);
  const byId = new Map(members.map((member) => [member.user_id, member]));

  const cancelEdit = () => {
    setEditingId(null);
    setEditBody("");
  };

  return (
    <Stack gap="sm">
      {comments.length === 0 && <Text size="sm" c="dimmed">No comments yet.</Text>}
      {comments.map((comment) => {
        const member = byId.get(comment.user_id);
        const isEditing = editingId === comment.id;
        return (
          <Group key={comment.id} align="flex-start" wrap="nowrap">
            <div
              style={{
                width: 8,
                height: 8,
                marginTop: 7,
                borderRadius: "50%",
                background: memberColor(member?.color ?? null),
              }}
            />
            <Stack gap={2} flex={1}>
              <Group gap="xs" wrap="wrap">
                <Text size="xs" fw={600}>{member?.display_name ?? "Member"}</Text>
                <Text size="xs" c="dimmed">
                  {dayjs(comment.created_at).format("MMM D, YYYY")}
                  {comment.edited_at ? " · edited" : ""}
                </Text>
                {comment.unit_group_key && (
                  <Badge size="xs" variant="light">
                    {unitGroupLabel(comment.unit_group_key)}
                  </Badge>
                )}
              </Group>
              {isEditing ? (
                <Stack gap="xs">
                  <Textarea
                    aria-label="Edit comment"
                    value={editBody}
                    onChange={(event) => setEditBody(event.currentTarget.value)}
                    minRows={2}
                    autoFocus
                  />
                  <Group justify="flex-end" gap="xs">
                    <Button size="xs" variant="subtle" onClick={cancelEdit}>Cancel</Button>
                    <Button
                      size="xs"
                      disabled={!editBody.trim()}
                      loading={update.isPending}
                      onClick={() =>
                        update.mutate(
                          { commentId: comment.id, body: editBody.trim() },
                          { onSuccess: cancelEdit },
                        )
                      }
                    >
                      Save
                    </Button>
                  </Group>
                </Stack>
              ) : (
                <Text size="sm">{comment.body}</Text>
              )}
            </Stack>
            {comment.user_id === session?.user.id && !isEditing && (
              <Menu position="right-start" withinPortal>
                <Menu.Target>
                  <ActionIcon size="sm" color="gray" aria-label="comment actions">
                    <IconDotsVertical size={14} stroke={1.5} />
                  </ActionIcon>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Item
                    leftSection={<IconPencil size={14} stroke={1.5} />}
                    onClick={() => {
                      setEditingId(comment.id);
                      setEditBody(comment.body);
                    }}
                  >
                    Edit
                  </Menu.Item>
                  <Menu.Item
                    color="red"
                    onClick={() => remove.mutate(comment.id)}
                    leftSection={<IconTrash size={14} stroke={1.5} />}
                  >
                    Delete
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            )}
          </Group>
        );
      })}
      <Textarea
        label="Add a comment"
        value={body}
        onChange={(event) => setBody(event.currentTarget.value)}
        minRows={2}
      />
      {currentUnitGroup ? (
        <Group justify="space-between" align="center" wrap="nowrap" gap="sm">
          <Checkbox
            label={`Only for Current Unit Group: ${currentUnitGroup.label}`}
            checked={scopeToCurrentGroup}
            onChange={(event) => setScopeToCurrentGroup(event.currentTarget.checked)}
          />
          <Button
            size="xs"
            disabled={!body.trim()}
            loading={create.isPending}
            onClick={() =>
              create.mutate(
                {
                  body: body.trim(),
                  unit_group_key: scopeToCurrentGroup ? currentUnitGroup.key : null,
                },
                {
                  onSuccess: () => {
                    setBody("");
                    setScopeToCurrentGroup(false);
                  },
                },
              )
            }
          >
            Comment
          </Button>
        </Group>
      ) : (
        <Group justify="flex-end">
          <Button
            size="xs"
            disabled={!body.trim()}
            loading={create.isPending}
            onClick={() =>
              create.mutate(
                { body: body.trim(), unit_group_key: null },
                {
                  onSuccess: () => {
                    setBody("");
                    setScopeToCurrentGroup(false);
                  },
                },
              )
            }
          >
            Comment
          </Button>
        </Group>
      )}
    </Stack>
  );
}
