// Account settings (P3-16, DESIGN §20 v3.27) at /account/:tab — the same shell
// the hunt settings page uses, account-scoped.
//
// Profile is how other people see you, Account is how you get in, and Alerts
// owns the account defaults inherited by every Hunt (P3-22).
import {
  Alert,
  Anchor,
  Avatar,
  Button,
  Group,
  Loader,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useQueryClient } from "@tanstack/react-query";
import {
  IconAlertTriangle,
  IconArrowLeft,
  IconBell,
  IconMail,
  IconUserCircle,
} from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { PublicPageShell } from "../components/PublicPageShell";
import { UserMenu } from "../components/UserMenu";
import { SectionCard } from "../components/SectionCard";
import { SettingsSaveBar, SettingsShell, type SettingsTab } from "../components/SettingsShell";
import { MemberColorControl } from "../features/collaboration/MemberColorControl";
import { memberColor } from "../features/collaboration/memberColors";
import { useHunts } from "../features/hunts/api";
import {
  NOTIFICATION_EVENTS,
  NOTIFICATION_LABELS,
  useAccountNotificationPreferences,
  useSaveAccountNotificationPreferences,
  type NotificationEvent,
} from "../features/notifications/api";
import { ApiError, apiFetch } from "../lib/apiClient";
import { useAuth } from "./useAuth";
import { useProfile } from "./profile";

const TABS: SettingsTab[] = [
  {
    value: "profile",
    label: "Profile",
    description: "Name, color",
    icon: <IconUserCircle size={16} stroke={1.6} />,
  },
  {
    value: "security",
    label: "Account",
    description: "Email, sign-in",
    icon: <IconMail size={16} stroke={1.6} />,
  },
  {
    value: "alerts",
    label: "Alerts",
    description: "Email notifications",
    icon: <IconBell size={16} stroke={1.6} />,
  },
];

function ProfilePanel() {
  const { session } = useAuth();
  const profile = useProfile(session?.user.id);
  const qc = useQueryClient();
  const { data: hunts = [] } = useHunts();

  const [name, setName] = useState("");
  const [color, setColor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hydrated = useRef(false);

  // Hydrate once from the loaded profile; later refetches must not clobber
  // in-progress edits.
  useEffect(() => {
    if (hydrated.current || !profile.data) return;
    hydrated.current = true;
    setName(profile.data.default_display_name);
    setColor(profile.data.default_color);
  }, [profile.data]);

  const saved = profile.data;
  const dirtyLabels: string[] = [];
  if (saved && name !== saved.default_display_name) dirtyLabels.push("display name");
  if (saved && (color ?? null) !== saved.default_color) dirtyLabels.push("color");

  const discard = () => {
    if (!saved) return;
    setName(saved.default_display_name);
    setColor(saved.default_color);
  };

  const save = async () => {
    if (!session) return;
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
    } catch (error) {
      notifications.show({
        title: "Couldn't save profile",
        message: error instanceof ApiError ? error.message : "Unexpected error",
        color: "red",
      });
    } finally {
      setBusy(false);
    }
  };

  if (profile.isLoading) return <Loader />;

  return (
    <>
      <SectionCard title="Profile" hint="Used across all hunts">
        <Stack gap="md">
          <Group gap="sm" wrap="nowrap">
            <Avatar
              size={52}
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
            <Stack gap={0} style={{ minWidth: 0 }}>
              <Text fw={600}>{name || "—"}</Text>
              <Text size="sm" c="dimmed" truncate>
                {session?.user.email}
              </Text>
            </Stack>
          </Group>

          <TextInput
            label="Default display name"
            description="Every hunt shows this unless you set a different name in that hunt's settings."
            maxLength={80}
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
          />

          <MemberColorControl
            value={color}
            loading={busy}
            onChange={setColor}
            label="Default color"
          />
        </Stack>
      </SectionCard>

      <SectionCard title="Where you're using this name">
        <Stack gap="xs">
          {hunts.length === 0 && (
            <Text size="sm" c="dimmed">
              You aren&apos;t a member of any hunts yet.
            </Text>
          )}
          {hunts.map((hunt) => (
            <Group key={hunt.id} justify="space-between" wrap="nowrap" gap="sm">
              <Text size="sm" truncate>
                {hunt.name}
              </Text>
              <Anchor component={Link} size="xs" to={`/h/${hunt.id}/settings/profile`}>
                Hunt profile
              </Anchor>
            </Group>
          ))}
        </Stack>
      </SectionCard>

      <SettingsSaveBar
        dirtyLabels={dirtyLabels}
        saving={busy}
        onSave={() => void save()}
        onDiscard={discard}
      />
    </>
  );
}

function AccountPanel() {
  const { session } = useAuth();
  const navigate = useNavigate();

  return (
    <>
      <SectionCard title="Sign-in">
        <Stack gap="md">
          {/* Fixed for the life of the account by decision, not by omission
              (DESIGN §18, 2026-07-29) — so it reads as a stated fact rather
              than a control that has not been built yet. */}
          <TextInput
            label="Email address"
            description="Your account is tied to this address and it can't be changed. A new address means a new account."
            value={session?.user.email ?? ""}
            readOnly
            disabled
          />
          <Stack gap={0} style={{ minWidth: 0 }}>
            <Text size="sm" fw={600}>
              Password
            </Text>
            <Text size="xs" c="dimmed">
              Set a password, or change the one you have.
            </Text>
          </Stack>
          <Button variant="default" onClick={() => navigate("/auth/reset-password")}>
            Change password
          </Button>
        </Stack>
      </SectionCard>

      <SectionCard title="Signing out">
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            Ends this session on this device. Your hunts, ratings, and comments are untouched.
          </Text>
          <Button variant="default" onClick={() => navigate("/signout")}>
            Sign out
          </Button>
        </Stack>
      </SectionCard>

      {/* Deletion is deferred, not declined — P3-23. Said plainly, with the
          one thing a person needs to know in the meantime. */}
      <Alert
        color="gray"
        variant="light"
        icon={<IconAlertTriangle size={16} stroke={1.6} />}
        title="Deleting your account isn't here yet"
      >
        <Text size="sm">
          It needs to deal with hunts you own before it can be safe to offer. Ask Yusuf and it can
          be done for you.
        </Text>
      </Alert>
    </>
  );
}

function AlertsPanel() {
  const preferences = useAccountNotificationPreferences();
  const savePreferences = useSaveAccountNotificationPreferences();
  const [email, setEmail] = useState<Record<NotificationEvent, boolean> | null>(null);

  useEffect(() => {
    if (email === null && preferences.data) setEmail(preferences.data.email);
  }, [email, preferences.data]);

  if (preferences.error) {
    return (
      <Alert color="red" title="Couldn't load alerts">
        {preferences.error.message}
      </Alert>
    );
  }
  if (!email || preferences.isLoading) return <Loader />;
  const dirtyLabels = NOTIFICATION_EVENTS.filter(
    (event) => email[event] !== preferences.data?.email[event],
  ).map((event) => NOTIFICATION_LABELS[event].label.toLowerCase());

  return (
    <>
      <SectionCard title="Email alerts" hint="Account defaults">
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            These defaults apply in every Hunt unless you choose a Hunt-specific override.
            Invitations are always emailed because the message is how the invitation arrives.
          </Text>
          {NOTIFICATION_EVENTS.map((event) => (
            <Switch
              key={event}
              label={NOTIFICATION_LABELS[event].label}
              description={NOTIFICATION_LABELS[event].description}
              checked={email[event]}
              onChange={(change) =>
                setEmail((current) => ({
                  ...(current ?? email),
                  [event]: change.currentTarget.checked,
                }))
              }
            />
          ))}
        </Stack>
      </SectionCard>
      <SettingsSaveBar
        dirtyLabels={dirtyLabels}
        saving={savePreferences.isPending}
        onDiscard={() => preferences.data && setEmail(preferences.data.email)}
        onSave={() =>
          savePreferences.mutate(
            { email },
            {
              onSuccess: () => notifications.show({ message: "Alert defaults saved", color: "green" }),
              onError: (error) =>
                notifications.show({
                  title: "Couldn't save alerts",
                  message: error instanceof ApiError ? error.message : "Unexpected error",
                  color: "red",
                }),
            },
          )
        }
      />
    </>
  );
}

export function AccountPage() {
  const { session } = useAuth();
  const { tab } = useParams();
  const navigate = useNavigate();
  const active = TABS.some((candidate) => candidate.value === tab) ? tab! : "profile";

  if (!session) return <Navigate to="/login" replace />;

  // /account sits outside any hunt, so there is no AppShell navbar here — the
  // public shell supplies the wordmark, scheme toggle, and account menu.
  return (
    <PublicPageShell containerSize="md" rightSlot={<UserMenu />}>
      <Stack gap="lg">
        <PageHeader
          title="Account settings"
          description="Defaults that follow you into every hunt"
          rightSlot={
            <Button
              component={Link}
              to="/"
              variant="subtle"
              color="gray"
              leftSection={<IconArrowLeft size={16} stroke={1.5} />}
            >
              Back to hunts
            </Button>
          }
        />
        <SettingsShell
          tabs={TABS}
          active={active}
          onSelect={(value) => navigate(`/account/${value}`)}
        >
          {active === "profile" ? (
            <ProfilePanel />
          ) : active === "alerts" ? (
            <AlertsPanel />
          ) : (
            <AccountPanel />
          )}
        </SettingsShell>
      </Stack>
    </PublicPageShell>
  );
}
