// Sources (P3-5, §13.2): retained links, fetch state, assurance badge, and the
// Listing's editable Source Policy. Relaxing the policy queues DISCOVER.
import { Anchor, Box, Group, Select, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconExternalLink } from "@tabler/icons-react";

import { SingleSourceBadge } from "../../components/badges/ListingBadges";
import { SOURCE_POLICIES, type SourcePolicy } from "../../lib/contracts";
import { usePatchSourcePolicy } from "./api";
import classes from "./SourcesList.module.css";
import type { PropertySource, SingleSourceReason } from "./types";

// The dimmed secondary text is the URL's path (the distinguishing part beyond
// the site_domain shown as the name) so a source never repeats its own domain.
function pathOf(url: string): string {
  try {
    const { pathname, search } = new URL(url);
    const rest = `${pathname}${search}`;
    return rest === "/" ? "" : rest;
  } catch {
    return url;
  }
}

function fetchTitle(source: PropertySource): string {
  if (!source.last_fetched_at) return "Not fetched yet";
  return `Last fetched ${new Date(source.last_fetched_at).toLocaleString()}`;
}

export function SourcesList({
  sources,
  sourcePolicy,
  huntId,
  listingId,
  singleSourceReason,
  canEdit,
}: {
  sources: PropertySource[];
  sourcePolicy: SourcePolicy;
  huntId: string;
  listingId: string;
  singleSourceReason: SingleSourceReason | null;
  canEdit: boolean;
}) {
  const patchPolicy = usePatchSourcePolicy(huntId);
  const changePolicy = (value: string | null) => {
    if (!value || value === sourcePolicy) return;
    patchPolicy.mutate(
      { listingId, sourcePolicy: value as SourcePolicy },
      {
        onError: (error) => notifications.show({
          color: "red",
          title: "Could not update Source Policy",
          message: error instanceof Error ? error.message : "Try again.",
        }),
      },
    );
  };
  return (
    <Stack gap="xs">
      {singleSourceReason && (
        <Box data-testid="single-source">
          <SingleSourceBadge reason={singleSourceReason} />
        </Box>
      )}
      {sources.map((source) => (
        <Group
          key={source.id}
          className={classes.source}
          title={fetchTitle(source)}
          wrap="nowrap"
          gap="xs"
          justify="center"
        >
          <Box
            component="span"
            className={`${classes.favdot} ${source.is_official ? classes.official : classes.neutral}`}
          />
          <Text size="sm" fw={600} className={classes.name}>
            {source.site_domain}
          </Text>
          <Text size="xs" c="dimmed" className={classes.host}>
            {pathOf(source.url)}
          </Text>
          {source.is_official && (
            <Text component="span" className={classes.tier}>
              official
            </Text>
          )}
          <Anchor
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className={classes.extLink}
            aria-label={`Open ${source.site_domain} in a new tab`}
          >
            <IconExternalLink size={15} stroke={1.5} />
          </Anchor>
        </Group>
      ))}
      {sources.length === 0 && (
        <Text size="sm" c="dimmed">
          No sources recorded yet.
        </Text>
      )}
      <Select
        label="Source Policy"
        description="Relaxing this policy starts a source-discovery refresh."
        data={SOURCE_POLICIES}
        value={sourcePolicy}
        onChange={changePolicy}
        disabled={!canEdit || patchPolicy.isPending}
        allowDeselect={false}
        size="xs"
      />
    </Stack>
  );
}
