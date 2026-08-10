// Shared table pagination (admin panel + Overview).
//
// Client-side slicing, deliberately: every list this serves is already in
// memory behind a sort and a filter the viewer set, and re-fetching per page
// would make "sort by spend" mean something different on page 2 than page 1.
// What it buys is render cost — a 5,000-row <table> is thousands of DOM nodes
// the browser lays out on every hover — not network cost. The network side of
// scale is a server-side concern (search endpoints, list caps), not this.
import { Group, Pagination, Select, Text } from "@mantine/core";
import { useLocalStorage } from "@mantine/hooks";
import { useEffect, useMemo, useState } from "react";

export const PAGE_SIZE_OPTIONS = [50, 100, 250] as const;
export type PageSize = (typeof PAGE_SIZE_OPTIONS)[number];

const DEFAULT_PAGE_SIZE: PageSize = 50;

/**
 * What the footer needs to render, whoever counted the rows.
 *
 * Split out from `PagedState` so a server-paged screen — which has a `total`
 * from the API and no local list to slice — drives the same control.
 */
export interface PageControls {
  page: number;
  setPage: (page: number) => void;
  pageSize: PageSize;
  setPageSize: (size: PageSize) => void;
  total: number;
  totalPages: number;
  /** 1-indexed bounds of the current page, for the "showing" line. */
  from: number;
  to: number;
}

export interface PagedState<T> extends PageControls {
  /** The current page's slice of the rows handed in. */
  items: T[];
}

/**
 * Page a list that is already loaded.
 *
 * `storageKey` scopes the remembered page size: rows-per-page is a per-screen
 * preference (250 Jobs is reasonable, 250 people is not) and it belongs to the
 * browser, not the account.
 */
export function usePagedRows<T>(rows: T[], storageKey: string): PagedState<T> {
  const [pageSize, setPageSize] = useLocalStorage<PageSize>({
    key: `manzil:page-size:${storageKey}`,
    defaultValue: DEFAULT_PAGE_SIZE,
    // Without this the first paint uses the default and then jumps, which on a
    // table means rows appearing and disappearing under the cursor.
    getInitialValueInEffect: false,
  });
  const [page, setPage] = useState(1);

  const total = rows.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // A filter that shrinks the list can strand the viewer past the end. Walking
  // them back to the last real page beats showing an empty table and blaming
  // the filter.
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * pageSize;
  const items = useMemo(
    () => rows.slice(start, start + pageSize),
    [rows, start, pageSize],
  );

  return {
    page: safePage,
    setPage,
    pageSize,
    setPageSize,
    items,
    total,
    totalPages,
    from: total === 0 ? 0 : start + 1,
    to: Math.min(start + pageSize, total),
  };
}

export interface PagerState {
  page: number;
  setPage: (page: number) => void;
  pageSize: PageSize;
  setPageSize: (size: PageSize) => void;
  /** Row offset to send with the request. */
  offset: number;
}

/**
 * The request half of server-side paging: what to ask for.
 *
 * Deliberately separate from `usePageControls`, and in this order, because the
 * count comes back *with* the page — the request cannot depend on a total the
 * response has not delivered yet. Splitting it makes that sequence explicit
 * instead of hiding a circular dependency inside one hook.
 */
export function usePagerState(storageKey: string): PagerState {
  const [pageSize, setPageSize] = useLocalStorage<PageSize>({
    key: `manzil:page-size:${storageKey}`,
    defaultValue: DEFAULT_PAGE_SIZE,
    getInitialValueInEffect: false,
  });
  const [page, setPage] = useState(1);
  return {
    page,
    setPage,
    pageSize,
    // Row 1 of the new window, as in the client-side case.
    setPageSize: (size) => {
      setPageSize(size);
      setPage(1);
    },
    offset: (page - 1) * pageSize,
  };
}

/**
 * The response half: what the footer should say, given the server's count.
 *
 * `total` is `undefined` until the first page lands. While it is, the control
 * reports the page it is on rather than clamping to 1 and fighting the fetch
 * in flight.
 */
export function usePageControls(pager: PagerState, total: number | undefined): PageControls {
  const { page, setPage, pageSize } = pager;
  const known = total ?? 0;
  const totalPages = Math.max(1, Math.ceil(known / pageSize));

  // Only clamp against a real count. Clamping against the `0` shown while
  // loading would yank the viewer to page 1 on every refetch.
  useEffect(() => {
    if (total !== undefined && page > totalPages) setPage(totalPages);
  }, [total, page, totalPages, setPage]);

  const start = (page - 1) * pageSize;
  return {
    ...pager,
    total: known,
    totalPages,
    from: known === 0 ? 0 : start + 1,
    to: Math.min(start + pageSize, known),
  };
}

const SIZE_DATA = PAGE_SIZE_OPTIONS.map((size) => ({
  value: String(size),
  label: `${size} / page`,
}));

/**
 * The footer that goes with `usePagedRows`.
 *
 * The rows-per-page Select is shown even on a single page — it is how the
 * viewer *gets* more rows, so hiding it when there is only one page hides the
 * control exactly when someone might want to widen the window. The page
 * numbers, which do nothing at that size, are the part that hides.
 */
export function TablePagination({
  state,
  noun = "rows",
}: {
  state: PageControls;
  /** Plural noun for the count line — "people", "Hunts", "Jobs". */
  noun?: string;
}) {
  if (state.total === 0) return null;

  return (
    <Group justify="space-between" align="center" wrap="wrap" gap="sm" px="md" py="xs">
      <Text size="xs" c="dimmed">
        Showing {state.from}–{state.to} of {state.total} {noun}
      </Text>
      <Group gap="sm" wrap="wrap" justify="flex-end">
        {state.totalPages > 1 && (
          <Pagination
            size="sm"
            withEdges
            siblings={1}
            total={state.totalPages}
            value={state.page}
            onChange={state.setPage}
            aria-label={`${noun} pages`}
          />
        )}
        <Select
          size="xs"
          w={110}
          aria-label="Rows per page"
          data={SIZE_DATA}
          value={String(state.pageSize)}
          allowDeselect={false}
          onChange={(value) => {
            if (!value) return;
            state.setPageSize(Number(value) as PageSize);
            // Row 1 of the new window rather than "wherever the old offset
            // lands", which after 50 → 250 is a page the viewer never chose.
            state.setPage(1);
          }}
        />
      </Group>
    </Group>
  );
}
