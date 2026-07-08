// TanStack Query client (IMPLEMENTATION §2: server state exclusively via Query,
// keyed by table+hunt; no useEffect data fetching).
import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});
