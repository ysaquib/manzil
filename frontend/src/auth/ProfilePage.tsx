// Account profile (/profile): the default display name and default color a
// Hunt membership inherits unless it carries its own override (set per hunt
// in Settings → Members). Batch-saved with one button; propagation matches
// the display-name rule that already ships.
import {
  Avatar,
  Button,
  Card,
  Center,
  Divider,
  Group,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useQueryClient } from "@tanstack/react-query";
import { IconArrowLeft } from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { PublicPageShell } from "../components/PublicPageShell";
import { UserMenu } from "../components/UserMenu";
import { MemberColorControl } from "../features/collaboration/MemberColorControl";
import { memberColor } from "../features/collaboration/memberColors";
import { ApiError, apiFetch } from "../lib/apiClient";
import { useAuth } from "./useAuth";
import { useProfile } from "./profile";

export function ProfilePage() {
  const { session } = useAuth();
  const profile = useProfile(session?.user.id);
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [color, setColor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hydrated = useRef(false);

  // Hydrate the form once from the loaded profile; later refetches must not
  // clobber in-progress edits.
  useEffect(() => {
    if (hydrated.current || !profile.data) return;
    hydrated.current = true;
    setName(profile.data.default_display_name);
    setColor(profile.data.default_color);
  }, [profile.data]);

  if (!session) return <Navigate to="/login" replace />;

  const dirty =
    profile.data !== null &&
    profile.data !== undefined &&
    (name !== profile.data.default_display_name || (color ?? null) !== profile.data.default_color);

  const save = async () => {
    setBusy(true);
    try {
      await apiFetch("/v1/profile", {
        method: "PUT",
        body: { default_display_name: name.trim(), default_color: color },
      });
      await qc.invalidateQueries({ queryKey: ["profile", session.user.id] });
      // Member lists resolve color/name fallbacks from the profile.
      await qc.invalidateQueries({ queryKey: ["hunt_members"] });
      notifications.show({ message: "Profile saved", color: "green" });
    } catch (e) {
      notifications.show({
        title: "Couldn't save profile",
        message: e instanceof ApiError ? e.message : "Unexpected error",
        color: "red",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <PublicPageShell rightSlot={<UserMenu />}>
      <Center>
        <Card withBorder w="100%" maw={480}>
          <Stack gap="md">
            <Group gap="sm" wrap="nowrap">
              <Avatar
                size={44}
                radius="xl"
                styles={{
                  placeholder: {
                    backgroundColor: memberColor(color),
                    color: "var(--mantine-color-white)",
                  },
                }}
              >
                {name.trim().charAt(0).toUpperCase() || "?"}
              </Avatar>
              <div>
                <Title order={3}>Your profile</Title>
                <Text size="sm" c="dimmed">
                  {session.user.email}
                </Text>
              </div>
            </Group>

            <Divider />

            <TextInput
              label="Default display name"
              description="Hunts show this name unless you set a different one in that hunt's settings."
              maxLength={80}
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
            />

            <div>
              <Text size="sm" fw={500} mb={2}>
                Default color
              </Text>
              <Text size="xs" c="dimmed" mb="xs">
                Marks your ratings and comments in hunts where you haven&apos;t picked a color.
              </Text>
              <MemberColorControl value={color} loading={busy} onChange={setColor} label="" />
            </div>

            <Group justify="space-between" mt="sm">
              <Button
                component={Link}
                to="/"
                variant="subtle"
                color="gray"
                leftSection={<IconArrowLeft size={16} stroke={1.5} />}
              >
                Back to hunts
              </Button>
              <Button onClick={() => void save()} loading={busy} disabled={!dirty || !name.trim()}>
                Save changes
              </Button>
            </Group>
          </Stack>
        </Card>
      </Center>
    </PublicPageShell>
  );
}
