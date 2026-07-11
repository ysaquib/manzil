import {
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Group,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Timeline,
} from "@mantine/core";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { useMembers } from "../collaboration/api";
import { useListings } from "../listings/api";
import { STATE_COLOR } from "./JobCard";
import { useHistoryJobs, useJobEvents, type Job } from "./api";
import { filterHistoryJobs, jobDuration } from "./history";

function EventTimeline({ jobId, expanded }: { jobId: string; expanded: boolean }) {
  const { data: events = [], error } = useJobEvents(jobId, expanded);
  if (error) return <Alert color="red">Couldn&apos;t load this run&apos;s timeline.</Alert>;
  if (events.length === 0) return <Text size="sm" c="dimmed">No stage events were recorded.</Text>;
  return (
    <Timeline bulletSize={16} lineWidth={2}>
      {events.map((event) => (
        <Timeline.Item key={event.id} title={`${event.stage}: ${event.event.replaceAll("_", " ")}`}>
          <Text size="xs" c="dimmed">{new Date(event.at).toLocaleString()}</Text>
          {Object.keys(event.detail ?? {}).length > 0 && (
            <Code block mt="xs">{JSON.stringify(event.detail, null, 2)}</Code>
          )}
        </Timeline.Item>
      ))}
    </Timeline>
  );
}

function HistoryCard({ job, listingName, memberName }: {
  job: Job;
  listingName: string | null;
  memberName: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const duration = jobDuration(job);
  return (
    <Card>
      <Stack gap="sm">
        <Group justify="space-between">
          <Group gap="xs">
            <Badge color="gray">{job.type}</Badge>
            <Text fw={600} size="sm">{listingName ?? "Hunt-wide run"}</Text>
          </Group>
          <Badge color={STATE_COLOR[job.state]}>{job.state}</Badge>
        </Group>
        <Text size="xs" c="dimmed">
          {memberName}{duration ? ` · ${duration}` : ""} · ${Number(job.cost_actual_usd).toFixed(4)} USD
        </Text>
        {job.error && <Alert color="red" title="Run failed">{job.error}</Alert>}
        {job.plan && (
          <div>
            <Text size="xs" fw={600} mb={4}>Plan manifest</Text>
            <Code block>{JSON.stringify(job.plan, null, 2)}</Code>
          </div>
        )}
        <Button variant="subtle" size="xs" onClick={() => setExpanded((value) => !value)}>
          {expanded ? "Hide timeline" : "Inspect timeline"}
        </Button>
        {expanded && <EventTimeline jobId={job.id} expanded={expanded} />}
      </Stack>
    </Card>
  );
}

export function TasksHistoryTab() {
  const { huntId = "" } = useParams();
  const { data: jobs = [], error } = useHistoryJobs(huntId);
  const { data: listings = [] } = useListings(huntId);
  const { data: members = [] } = useMembers(huntId);
  const [listingFilter, setListingFilter] = useState<string | null>(null);
  const [memberFilter, setMemberFilter] = useState<string | null>(null);
  const [outcomeFilter, setOutcomeFilter] = useState<string | null>(null);

  const listingById = new Map(listings.map((listing) => [listing.id, listing]));
  const memberById = new Map(members.map((member) => [member.user_id, member]));
  const filtered = filterHistoryJobs(
    jobs,
    { listingId: listingFilter, memberId: memberFilter, outcome: outcomeFilter },
    new Map(listings.map((listing) => [listing.id, listing.added_by])),
  );

  if (error) return <Alert color="red">Couldn&apos;t load task history.</Alert>;
  return (
    <Stack gap="md">
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <Select clearable label="Listing" value={listingFilter} onChange={setListingFilter}
          data={listings.map((listing) => ({ value: listing.id, label: listing.property.name }))} />
        <Select clearable label="Member" value={memberFilter} onChange={setMemberFilter}
          data={members.map((member) => ({ value: member.user_id, label: member.display_name ?? "Member" }))} />
        <Select clearable label="Outcome" value={outcomeFilter} onChange={setOutcomeFilter}
          data={["done", "failed", "cancelled"]} />
      </SimpleGrid>
      {filtered.length === 0 && <Card><Text c="dimmed" size="sm">No past runs match these filters.</Text></Card>}
      {filtered.map((job) => {
        const listing = job.hunt_listing_id ? listingById.get(job.hunt_listing_id) : null;
        const member = listing ? memberById.get(listing.added_by) : null;
        return (
          <HistoryCard key={job.id} job={job} listingName={listing?.property.name ?? null}
            memberName={listing ? (member?.display_name ?? "Member") : "system"} />
        );
      })}
    </Stack>
  );
}
