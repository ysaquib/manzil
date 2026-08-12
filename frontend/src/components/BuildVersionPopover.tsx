import { Box, Popover, Stack, Text, UnstyledButton } from "@mantine/core";

import {
  buildsDiffer,
  frontendBuildInfo,
  shortBuildSha,
  useApiBuildInfo,
} from "../lib/buildInfo";

function Artifact({ label, release, sha }: { label: string; release: string; sha: string }) {
  return (
    <Box>
      <Text size="xs" fw={700}>{label}</Text>
      <Text size="xs" ff="monospace">release {release}</Text>
      <Text size="xs" ff="monospace" style={{ overflowWrap: "anywhere" }}>build {sha}</Text>
    </Box>
  );
}

export function BuildVersionPopover() {
  const api = useApiBuildInfo();
  const mismatch = buildsDiffer(frontendBuildInfo, api.data);

  return (
    <Popover width={300} position="top" withArrow shadow="md">
      <Popover.Target>
        <UnstyledButton
          aria-label={`Frontend release ${frontendBuildInfo.release_version}, build ${shortBuildSha(frontendBuildInfo)}. Open build details.`}
          style={{ alignSelf: "center" }}
        >
          <Text size="xs" c="dimmed" ta="center" ff="monospace">
            v{frontendBuildInfo.release_version} · {shortBuildSha(frontendBuildInfo)}
          </Text>
        </UnstyledButton>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="sm">
          <Artifact
            label="Frontend"
            release={frontendBuildInfo.release_version}
            sha={frontendBuildInfo.build_sha}
          />
          {api.data ? (
            <Artifact label="API" release={api.data.release_version} sha={api.data.build_sha} />
          ) : (
            <Text size="xs" c="dimmed">
              API build information is unavailable.
            </Text>
          )}
          {mismatch && (
            <Text size="xs" c="dimmed">
              Different deploys — frontend and API release independently.
            </Text>
          )}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
