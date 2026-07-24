// Sources (P3-5, §13.2): retained links, fetch state, assurance badge, and the
// Listing's editable Source Policy. Relaxing the policy queues DISCOVER.
import { Anchor, Select, Stack, Text } from "@mantine/core";
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
        <div data-testid="single-source">
          <SingleSourceBadge reason={singleSourceReason} />
        </div>
      )}
      {sources.map((source) => (
        <div key={source.id} className={classes.source} title={fetchTitle(source)}>
          <span
            className={`${classes.favdot} ${source.is_official ? classes.official : classes.neutral}`}
          />
          <span className={classes.name}>{source.site_domain}</span>
          <span className={classes.host}>{pathOf(source.url)}</span>
          {source.is_official && <span className={classes.tier}>official</span>}
          <Anchor
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className={classes.extLink}
            aria-label={`Open ${source.site_domain} in a new tab`}
          >
            <IconExternalLink size={15} stroke={1.5} />
          </Anchor>
        </div>
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
