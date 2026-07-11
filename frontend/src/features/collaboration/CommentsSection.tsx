import { ActionIcon, Button, Group, Stack, Text, Textarea } from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { useState } from "react";

import { useAuth } from "../../auth/useAuth";
import { useComments, useCreateComment, useDeleteComment, type HuntMember } from "./api";
import { memberColor } from "./memberColors";

export function CommentsSection({ listingId, members }: { listingId: string; members: HuntMember[] }) {
  const { session } = useAuth();
  const [body, setBody] = useState("");
  const { data: comments = [] } = useComments(listingId);
  const create = useCreateComment(listingId);
  const remove = useDeleteComment(listingId);
  const byId = new Map(members.map((member) => [member.user_id, member]));

  return (
    <Stack gap="sm">
      {comments.length === 0 && <Text size="sm" c="dimmed">No comments yet.</Text>}
      {comments.map((comment) => {
        const member = byId.get(comment.user_id);
        return (
          <Group key={comment.id} align="flex-start" wrap="nowrap">
            <div style={{ width: 8, height: 8, marginTop: 7, borderRadius: "50%", background: memberColor(member?.color ?? null) }} />
            <div style={{ flex: 1 }}>
              <Text size="xs" fw={600}>{member?.display_name ?? "Member"}</Text>
              <Text size="sm">{comment.body}</Text>
            </div>
            {comment.user_id === session?.user.id && (
              <ActionIcon aria-label="delete comment" onClick={() => remove.mutate(comment.id)}>
                <IconTrash size={14} />
              </ActionIcon>
            )}
          </Group>
        );
      })}
      <Textarea label="Add a comment" value={body} onChange={(event) => setBody(event.currentTarget.value)} minRows={2} />
      <Group justify="flex-end">
        <Button size="xs" disabled={!body.trim()} loading={create.isPending} onClick={() => create.mutate(body.trim(), { onSuccess: () => setBody("") })}>
          Comment
        </Button>
      </Group>
    </Stack>
  );
}
