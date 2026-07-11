// Tasks — Active tab. P2-5 Realtime keeps the Jobs query current; the manual
// refresh remains a user-controlled recovery action. History arrives in P2-7.
import { Alert, Button, Card, Center, Flex, Loader, SimpleGrid, Stack, Text } from "@mantine/core";
import { IconList, IconRefresh } from "@tabler/icons-react";
import { Link, useParams } from "react-router-dom";

import { semantic } from "../../theme";
import { useListings } from "../listings/api";
import { JobCard } from "./JobCard";
import { useActiveJobs, useAnswerCheckpoint, useCancelJob, useRetryJob } from "./api";
import { useEffect, useState } from "react";

export function TasksActivePage() {
  const { huntId = "" } = useParams();
  const { data: jobs, isLoading, error, refetch, isFetching, isRefetching } = useActiveJobs(huntId);
  const { data: listings } = useListings(huntId);
  const cancelJob = useCancelJob(huntId);
  const retryJob = useRetryJob(huntId);
  const answerCheckpoint = useAnswerCheckpoint(huntId);

  const nameByListing = new Map(
    (listings ?? []).map((listing) => [listing.id, listing.property.name]),
  );
  const busy = cancelJob.isPending || retryJob.isPending || answerCheckpoint.isPending;

  const [isRefreshing, setIsRefreshing] = useState(false);

  // async function withMinimumDuration<T>(promise: Promise<T>, ms = 1000): Promise<T> {
  //   const [result] = await Promise.all([promise, new Promise<void>((r) => setTimeout(r, ms))]);
  //   return result;
  // }

  // Refreshing state management to avoid flickering and ensure minimum duration
  // Side effect: this will always set isRefreshing back to false 0.5 seconds after done refreshing
  useEffect(() => {
    if (isRefetching || isFetching) {
      setIsRefreshing(true);
    }
    if (!isRefetching && !isFetching) {
      setTimeout(() => {
        setIsRefreshing(false);
      }, 500); // 0.5 second minimum duration
    }
  }, [isRefetching, isFetching]);

  return (
    <Stack gap="lg">
      <Flex
        justify="flex-end"
      >
        <Button 
          size="compact-xs" 
          variant="outline" 
          onClick={() => refetch()} 
          disabled={isRefreshing || isRefetching || isFetching}
          leftSection={isRefreshing || isRefetching || isFetching 
              ? <Loader size="xs" color="gray" /> 
              : <IconRefresh size={12} />}
        >
          {isRefreshing || isRefetching || isFetching ? "Refreshing..." : "Refresh"}
        </Button>
      </Flex>
      {isLoading && (
        <Center py="xl">
          <Stack align="center" gap="xs">
            <Loader />
            <Text size="sm" c="dimmed">
              Checking on your jobs…
            </Text>
          </Stack>
        </Center>
      )}
      {error && (
        <Alert color="red" title="Couldn't load jobs">
          {error.message} — try reloading the page.
        </Alert>
      )}
      {jobs && jobs.length === 0 && (
        <Card py="lg">
          <Stack align="center" gap="sm">
            <IconList size={28} stroke={1.5} color="var(--mantine-color-dimmed)" />
            <Text c="dimmed" size="sm" ta="center">
              All quiet — nothing running right now.{" "}
              <Text component={Link} to={`/h/${huntId}`} span c={semantic.active} inherit>
                Submit a listing from Overview
              </Text>{" "}
              and its progress lands here.
            </Text>
          </Stack>
        </Card>
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
