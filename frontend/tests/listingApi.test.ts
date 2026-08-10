import { describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/supabase", () => ({ supabase: {} }));
vi.mock("../src/lib/apiClient", () => ({ apiFetch: vi.fn() }));
vi.mock("../src/features/admin/useGhostMode", () => ({
  useGhostMutationPath: () => (path: string) => path,
}));

import { LISTING_SELECT } from "../src/features/listings/api";

describe("LISTING_SELECT", () => {
  it("does not request service-role-only cleaned Source text", () => {
    expect(LISTING_SELECT).not.toContain("property_sources(*)");
    expect(LISTING_SELECT).toContain(
      "property_sources(id,property_id,url,site_domain,is_official,last_fetched_at,last_success_at)",
    );
  });
});
