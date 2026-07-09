// Tasks — Active tab (P1-13): job cards polled at 3s via the one apiClient
// read (queued, running, waiting_user). Realtime replaces the polling in
// P2-4; the History tab is P2-6.
import { Alert, Center, Loader, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useParams } from "react-router-dom";

import { useListings } from "../listings/api";
import { JobCard } from "./JobCard";
import { useActiveJobs, useAnswerCheckpoint, useCancelJob, useRetryJob } from "./api";

export function TasksActivePage() {
  const { huntId = "" } = useParams();
  const { data: jobs, isLoading, error } = useActiveJobs(huntId);
  const { data: listings } = useListings(huntId);
  const cancelJob = useCancelJob(huntId);
  const retryJob = useRetryJob(huntId);
  const answerCheckpoint = useAnswerCheckpoint(huntId);

  const nameByListing = new Map(
    (listings ?? []).map((listing) => [listing.id, listing.property.name]),
  );
  const busy = cancelJob.isPending || retryJob.isPending || answerCheckpoint.isPending;

  return (
    <Stack gap="lg">
      <Title order={2}>Tasks</Title>
      {isLoading && (
        <Center py="xl">
          <Loader />
        </Center>
      )}
      {error && (
        <Alert color="red" title="Couldn't load jobs">
          {error.message}
        </Alert>
      )}
      {jobs && jobs.length === 0 && (
        <Text c="dimmed" size="sm">
          Nothing running. Submit a listing from the Overview to start a job.
        </Text>
      )}
      {jobs && jobs.length > 0 && (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
          {jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              listingName={
                job.hunt_listing_id ? (nameByListing.get(job.hunt_listing_id) ?? null) : null
              }
              onCancel={() => cancelJob.mutate(job.id)}
              onRetry={() => retryJob.mutate(job.id)}
              onAnswer={(choice, text) => answerCheckpoint.mutate({ jobId: job.id, choice, text })}
              busy={busy}
            />
          ))}
        </SimpleGrid>
      )}
    </Stack>
  );
}
