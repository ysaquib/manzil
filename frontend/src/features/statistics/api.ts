import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";
import { browserTimezone } from "../../lib/calendarDays";

export type StatisticsDays = 7 | 14 | 30 | 90 | 365;

export interface HuntStatisticsPoint {
  day: string;
  billed_cost_usd: number;
  deleted_cost_usd: number;
  listing_submissions: number;
  jobs_completed: number;
  jobs_failed: number;
  llm_calls: number;
  fetch_calls: number;
}

export interface HuntStatisticsReport {
  days: number;
  timezone: string;
  summary: Omit<HuntStatisticsPoint, "day">;
  daily: HuntStatisticsPoint[];
}

export function useHuntStatistics(huntId: string, days: StatisticsDays, enabled = true) {
  const timezone = browserTimezone();
  return useQuery({
    queryKey: ["hunt-statistics", huntId, days, timezone],
    queryFn: () =>
      apiFetch<HuntStatisticsReport>(
        `/v1/hunts/${huntId}/statistics?days=${days}&timezone=${encodeURIComponent(timezone)}`,
      ),
    enabled: Boolean(huntId) && enabled,
  });
}
