// TanStack Query client (IMPLEMENTATION §2: server state exclusively via Query,
// keyed by table+hunt; no useEffect data fetching).
import { QueryClient } from "@tanstack/react-query";

import { isDemo } from "./demo";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: isDemo()
      ? // In demo mode the cache *is* the database. A demo write never leaves
        // the tab (apiClient.ts), so it exists only as the optimistic update in
        // the cache — and any refetch would replace it with the server's
        // unchanged row, making the visitor's edit visibly undo itself a moment
        // after they made it.
        { staleTime: Infinity, refetchOnWindowFocus: false, refetchOnMount: false }
      : { staleTime: 30_000, refetchOnWindowFocus: false },
  },
});

if (isDemo()) {
  // The same problem from the other direction: nearly every mutation calls
  // `invalidateQueries` on success, which refetches regardless of staleTime.
  //
  // Overriding a library method is not something to do lightly, and it is done
  // here rather than in each feature for a specific reason: there are a dozen
  // `api.ts` files and the failure mode of missing one is silent and
  // intermittent — an edit that sticks on most screens and flickers back on
  // one. One seam, loudly commented, beats twelve chances to forget.
  //
  // Scoped to demo sessions; a real user's client is untouched.
  queryClient.invalidateQueries = async () => {};
}
