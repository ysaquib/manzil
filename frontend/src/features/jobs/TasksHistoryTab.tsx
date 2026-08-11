import { Alert, Anchor, Button, Card, Select, SimpleGrid, Stack, Text } from "@mantine/core";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { sentenceCase } from "../../lib/text";
import { useHuntContributors } from "../collaboration/api";
import { contributorDisplayName } from "../collaboration/memberDisplay";
import { useListings } from "../listings/api";
import classes from "./HistoryCard.module.css";
import { JobCardHeader } from "./JobCardHeader";
import { JobWarnings } from "./JobWarnings";
import { PipelineTrack } from "./PipelineTrack";
import { phasesForJob } from "./pipelinePhases";
import { useHistoryJobs, useJobEvents, useRetryJob, type JobEvent, type Job } from "./api";
import { filterHistoryJobs, formatJobCostUsd, historySpendLabel, jobDuration } from "./history";

// A stage event reads as a failure when its name mentions failing or erroring.
function isFailureEvent(event: JobEvent): boolean {
  return /fail|error/i.test(event.event);
}

function EventTimeline({ jobId, expanded }: { jobId: string; expanded: boolean }) {
  const { data: events = [], error } = useJobEvents(jobId, expanded);
  if (error) {
    return <div className={classes.timeline}><Text size="sm" c="red">Couldn&apos;t load this run&apos;s timeline.</Text></div>;
  }
  if (events.length === 0) {
    return <div className={classes.timeline}><Text size="sm" c="dimmed">No stage events were recorded.</Text></div>;
  }
  return (
    <div className={classes.timeline}>
      {events.map((event) => {
        const bad = isFailureEvent(event);
        const hasDetail = Object.keys(event.detail ?? {}).length > 0;
        return (
          <div key={event.id} className={classes.tlItem} data-tone={bad ? "failed" : "done"}>
            <span className={classes.tlBullet} />
            <div className={classes.tlBody}>
              <div className={classes.tlLine}>
                <span className={classes.tlStage}>{event.stage}</span>
                <span className={classes.tlEvent} data-bad={bad || undefined}>
                  {event.event.replaceAll("_", " ")}
                </span>
                <span className={classes.tlTime}>{new Date(event.at).toLocaleTimeString()}</span>
              </div>
              {hasDetail && <pre className={classes.code}>{JSON.stringify(event.detail, null, 2)}</pre>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function jobMeta(job: Job, memberName: string): string {
  const parts = [memberName];
  if (job.attempts > 1) parts.push(`attempt ${job.attempts}`);
  const duration = jobDuration(job);
  if (duration) parts.push(duration);
  parts.push(formatJobCostUsd(job.cost_actual_usd));
  return parts.join(" · ");
}

function escalationSummary(plan: unknown): string | null {
  const rounds = (
    plan as {
      escalation?: {
        rounds?: Array<{
          kind?: string;
          trigger_targets?: unknown[];
          sources?: Array<{ url?: string }>;
        }>;
      };
    } | null
  )?.escalation?.rounds;
  if (!rounds?.length) return null;
  const sourceCount = rounds.reduce((total, round) => total + (round.sources?.length ?? 0), 0);
  const targetCount = new Set(rounds.flatMap((round) => round.trigger_targets ?? [])).size;
  return `Cross-check escalated ${rounds.length} time${rounds.length === 1 ? "" : "s"} · ${sourceCount} additional Source${sourceCount === 1 ? "" : "s"} · ${targetCount} unresolved field${targetCount === 1 ? "" : "s"}`;
}

function HistoryCard({ job, listingName, memberName, onRetry, retrying }: {
  job: Job;
  listingName: string | null;
  memberName: string;
  onRetry: () => void;
  retrying: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [planExpanded, setPlanExpanded] = useState(false);
  const canRetry = job.state === "failed" || job.state === "cancelled";
  const togglePlan = () => setPlanExpanded((value) => !value);
  const escalation = escalationSummary(job.plan);

  return (
    <Card className={classes.card}>
      <JobCardHeader state={job.state} type={job.type} title={listingName ?? "Hunt-wide run"} />
      <PipelineTrack
        model={phasesForJob(job)}
        expandable
        expanded={expanded}
        onToggle={() => setExpanded((value) => !value)}
      >
        <EventTimeline jobId={job.id} expanded={expanded} />
      </PipelineTrack>
      {job.error && <div className={classes.error}>{job.error}</div>}
      <JobWarnings warnings={job.warnings} />
      {escalation && (
        <Text size="xs" c="dimmed">
          {escalation}
        </Text>
      )}
      {job.plan && planExpanded && (
        <div>
          <div className={classes.planHeader}>
            <Text size="xs" fw={600}>Plan manifest</Text>
            <Anchor component="button" type="button" size="xs" c="dimmed" onClick={togglePlan}>
              Hide plan
            </Anchor>
          </div>
          <pre className={classes.code}>{JSON.stringify(job.plan, null, 2)}</pre>
        </div>
      )}
      <div className={classes.footer}>
        <span className={classes.meta}>{jobMeta(job, memberName)}</span>
        <div className={classes.actions}>
          {job.plan && (
            <Anchor component="button" type="button" size="xs" c="dimmed" onClick={togglePlan}>
              {planExpanded ? "Hide plan" : "Inspect plan"}
            </Anchor>
          )}
          {canRetry && (
            <Button size="xs" variant="light" color="grape" onClick={onRetry} loading={retrying}>
              Retry
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}

export function TasksHistoryTab() {
  const { huntId = "" } = useParams();
  const { data: jobs = [], error } = useHistoryJobs(huntId);
  const { data: listings = [] } = useListings(huntId);
  const { data: contributors = [] } = useHuntContributors(huntId);
  const retryJob = useRetryJob(huntId);
  const [listingFilter, setListingFilter] = useState<string | null>(null);
  const [memberFilter, setMemberFilter] = useState<string | null>(null);
  const [outcomeFilter, setOutcomeFilter] = useState<string | null>(null);

  const listingById = new Map(listings.map((listing) => [listing.id, listing]));
  const contributorById = new Map(
    contributors.map((contributor) => [contributor.user_id, contributor]),
  );
  const filters = { listingId: listingFilter, memberId: memberFilter, outcome: outcomeFilter };
  const addedByByListing = new Map(listings.map((listing) => [listing.id, listing.added_by]));
  const submitterIds = new Set(addedByByListing.values());
  const submitterOptions = contributors
    .filter((contributor) => submitterIds.has(contributor.user_id))
    .map((contributor) => ({
      value: contributor.user_id,
      label: contributorDisplayName(contributor),
    }));
  const filtered = filterHistoryJobs(jobs, filters, addedByByListing);
  const filtersActive = listingFilter !== null || memberFilter !== null || outcomeFilter !== null;

  if (error) return <Alert color="red">Couldn&apos;t load task history.</Alert>;
  return (
    <Stack gap="md">
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <Select clearable label="Listing" value={listingFilter} onChange={setListingFilter}
          data={listings.map((listing) => ({ value: listing.id, label: listing.property.name }))} />
        <Select clearable label="Submitted by" value={memberFilter} onChange={setMemberFilter}
          data={submitterOptions} />
        <Select clearable label="Outcome" value={outcomeFilter} onChange={setOutcomeFilter}
          data={["done", "failed", "cancelled"].map((outcome) => ({
            value: outcome,
            label: sentenceCase(outcome),
          }))} />
      </SimpleGrid>
      {jobs.length > 0 && (
        <Text size="sm" c="dimmed" ta="right" style={{ fontVariantNumeric: "tabular-nums" }}>
          {historySpendLabel(filtered, jobs, filtersActive)}
        </Text>
      )}
      {filtered.length === 0 && <Card><Text c="dimmed" size="sm">No past runs match these filters.</Text></Card>}
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
        {filtered.map((job) => {
          const listing = job.hunt_listing_id ? listingById.get(job.hunt_listing_id) : null;
          const contributor = listing ? contributorById.get(listing.added_by) : null;
          return (
            <HistoryCard key={job.id} job={job} listingName={listing?.property.name ?? null}
              memberName={listing ? contributorDisplayName(contributor) : "system"}
              onRetry={() => retryJob.mutate(job.id)}
              retrying={retryJob.isPending && retryJob.variables === job.id} />
          );
        })}
      </SimpleGrid>
    </Stack>
  );
}
