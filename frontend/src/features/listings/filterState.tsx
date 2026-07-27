// Hunt-scoped Overview filter state (§13.2), lifted out of OverviewPage so the
// Overview table and the Map view (§20 2026-07-26) filter the same set — a map
// that disagreed with the table it sits next to would be worse than no map.
//
// Provider lives in AppLayout, above the hunt's Outlet, so switching tabs keeps
// the filters; switching hunts remounts it (keyed on huntId) and re-seeds.
import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { notifications } from "@mantine/notifications";

import { useCurrentMember } from "../collaboration/api";
import { usePublishSharedFilters, useSharedFilters } from "../hunts/api";
import {
  DEFAULT_OVERVIEW_FILTERS,
  hasActiveFilters,
  sanitizeFilterState,
  type OverviewFilterState,
} from "./overviewRows";

export interface OverviewFiltersValue {
  filters: OverviewFilterState;
  setFilters: (next: OverviewFilterState) => void;
  /** The published hunt-wide set, or null when none is published. */
  sharedFilters: OverviewFilterState | null;
  canPublish: boolean;
  publish: (next: OverviewFilterState) => void;
  publishPending: boolean;
}

const OverviewFiltersContext = createContext<OverviewFiltersValue | null>(null);

export function OverviewFiltersProvider({
  huntId,
  children,
}: {
  huntId: string;
  children: ReactNode;
}) {
  const [filters, setFiltersState] = useState<OverviewFilterState>(DEFAULT_OVERVIEW_FILTERS);

  // Hunt-wide filters (§13.2, §20 2026-07-19): the published set seeds the
  // local state once per mount — after that the member deviates freely.
  const { data: sharedRow } = useSharedFilters(huntId);
  const publishFilters = usePublishSharedFilters(huntId);
  const { data: currentMember } = useCurrentMember(huntId);
  const sharedFilters = useMemo(
    () => (sharedRow ? sanitizeFilterState(sharedRow.filters) : null),
    [sharedRow],
  );
  const touchedRef = useRef(false);
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current || sharedFilters === null) return;
    seededRef.current = true;
    if (hasActiveFilters(sharedFilters) && !touchedRef.current) setFiltersState(sharedFilters);
  }, [sharedFilters]);

  const value = useMemo<OverviewFiltersValue>(
    () => ({
      filters,
      setFilters: (next) => {
        touchedRef.current = true;
        setFiltersState(next);
      },
      sharedFilters,
      canPublish: currentMember?.role === "owner" || currentMember?.role === "curator",
      publish: (next) =>
        publishFilters.mutate({ ...next }, {
          onSuccess: () =>
            notifications.show({
              message: hasActiveFilters(next)
                ? "Filters applied hunt-wide — members start from this view."
                : "Hunt-wide filters cleared.",
            }),
        }),
      publishPending: publishFilters.isPending,
    }),
    [filters, sharedFilters, currentMember, publishFilters],
  );

  return (
    <OverviewFiltersContext.Provider value={value}>{children}</OverviewFiltersContext.Provider>
  );
}

export function useOverviewFilters(): OverviewFiltersValue {
  const value = useContext(OverviewFiltersContext);
  if (!value) {
    throw new Error("useOverviewFilters must be used inside an OverviewFiltersProvider");
  }
  return value;
}
