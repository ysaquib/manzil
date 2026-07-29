// Drawer state lives in the URL (P3-16, DESIGN §20 v3.27).
//
// Query params rather than path segments: filters, sort, and the compare set
// already ride the query string, and the page underneath the Drawer stays
// mounted. `?listing=…&group=…&plan=…&tab=…`.
//
// One reader. The Drawer renders from `useSearchParams` and nothing else — a
// second copy in component state is how the URL and the open Drawer drift
// apart, which is exactly the bug this replaces.
//
// History: opening **pushes**, so Back closes the Drawer, which is the gesture
// people already expect. Closing and tab changes **replace**, so Back never
// walks the reader out through five tabs.
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import type { DrawerSelection } from "./ListingDetailDrawer";

export const LISTING_PARAM = "listing";
export const GROUP_PARAM = "group";
export const PLAN_PARAM = "plan";
export const TAB_PARAM = "tab";

const DRAWER_PARAMS = [LISTING_PARAM, GROUP_PARAM, PLAN_PARAM, TAB_PARAM] as const;

export interface DrawerRoute {
  /** Null when no Drawer is addressed by the current URL. */
  selection: DrawerSelection | null;
  /**
   * What the Drawer should render. Holds the closing Drawer's selection until
   * its exit transition finishes — clearing the URL is instant, and an emptied
   * Drawer sliding out is worse than no animation at all.
   */
  renderSelection: DrawerSelection | null;
  planId: string | null;
  tab: string | null;
  opened: boolean;
  open: (listingId: string, groupKey: string | null) => void;
  close: () => void;
  /** Hand to the Drawer's `onExited` so the lingering selection is released. */
  onExited: () => void;
  setPlan: (planId: string | null) => void;
  setTab: (tab: string | null) => void;
}

/** Pure: the params an open Drawer contributes. Exported for tests. */
export function drawerParams(
  listingId: string,
  groupKey: string | null,
): Record<string, string> {
  const params: Record<string, string> = { [LISTING_PARAM]: listingId };
  if (groupKey !== null) params[GROUP_PARAM] = groupKey;
  return params;
}

/** Pure: read a selection out of a param bag, or null when none is addressed. */
export function readSelection(params: URLSearchParams): DrawerSelection | null {
  const listingId = params.get(LISTING_PARAM);
  if (!listingId) return null;
  return { listingId, groupKey: params.get(GROUP_PARAM) };
}

/** Pure: strip every Drawer param, leaving filters and sort untouched. */
export function withoutDrawer(params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const key of DRAWER_PARAMS) next.delete(key);
  return next;
}

export function useDrawerRoute(): DrawerRoute {
  const [searchParams, setSearchParams] = useSearchParams();

  const selection = useMemo(() => readSelection(searchParams), [searchParams]);

  const [lingering, setLingering] = useState<DrawerSelection | null>(selection);
  useEffect(() => {
    if (selection) setLingering(selection);
  }, [selection]);

  const open = useCallback(
    (listingId: string, groupKey: string | null) => {
      const next = withoutDrawer(searchParams);
      for (const [key, value] of Object.entries(drawerParams(listingId, groupKey))) {
        next.set(key, value);
      }
      setSearchParams(next);
    },
    [searchParams, setSearchParams],
  );

  const close = useCallback(() => {
    setSearchParams(withoutDrawer(searchParams), { replace: true });
  }, [searchParams, setSearchParams]);

  const setPlan = useCallback(
    (planId: string | null) => {
      const next = new URLSearchParams(searchParams);
      if (planId) next.set(PLAN_PARAM, planId);
      else next.delete(PLAN_PARAM);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const setTab = useCallback(
    (tab: string | null) => {
      const next = new URLSearchParams(searchParams);
      if (tab) next.set(TAB_PARAM, tab);
      else next.delete(TAB_PARAM);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  return {
    selection,
    renderSelection: selection ?? lingering,
    onExited: () => setLingering(null),
    planId: searchParams.get(PLAN_PARAM),
    tab: searchParams.get(TAB_PARAM),
    opened: selection !== null,
    open,
    close,
    setPlan,
    setTab,
  };
}
