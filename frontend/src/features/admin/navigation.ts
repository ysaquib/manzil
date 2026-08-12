import type { AdminSearchMode } from "./api";

export const ADMIN_SEARCH_MODE_OPTIONS: { value: AdminSearchMode; label: string }[] = [
  { value: "text", label: "Search text" },
  { value: "id", label: "Search by ID" },
];

export function adminSearchMode(value: string | null): AdminSearchMode {
  return value === "id" ? "id" : "text";
}

/**
 * Cross-panel links deliberately carry both the exact-ID search and selection.
 * The receiving page stays URL-addressable, waits for its list query to settle,
 * then opens the referenced row rather than relying on transient router state.
 */
export function adminDirectoryLink(
  section: "hunts" | "people" | "jobs",
  id: string,
): string {
  const params = new URLSearchParams({
    search: id,
    search_mode: "id",
    selected: id,
  });
  return `/admin/${section}?${params.toString()}`;
}
