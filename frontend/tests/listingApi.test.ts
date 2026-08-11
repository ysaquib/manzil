import { describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/supabase", () => ({ supabase: {} }));
vi.mock("../src/lib/apiClient", () => ({ apiFetch: vi.fn() }));
vi.mock("../src/features/admin/useGhostMode", () => ({
  useGhostMutationPath: () => (path: string) => path,
}));

import { LISTING_SELECT, selectPropertyImageRows } from "../src/features/listings/api";

describe("LISTING_SELECT", () => {
  it("does not request service-role-only cleaned Source text", () => {
    expect(LISTING_SELECT).not.toContain("property_sources(*)");
    expect(LISTING_SELECT).toContain(
      "property_sources(id,property_id,url,site_domain,is_official,last_fetched_at,last_success_at)",
    );
  });
});

describe("gallery image projection", () => {
  const row = (id: string, kind: "listing_photo" | "floor_plan_diagram" | "other", scene?: string) => ({
    id,
    storage_path: `${id}.webp`,
    width: 1200,
    height: 800,
    kind,
    vision_assessment: scene
      ? { classification: { assessment: { predicted_scene: scene, kitchen_score: 0.1 } } }
      : null,
  });

  it("fills 30 photo slots from eligible classified images and keeps diagrams separate", () => {
    const candidates = [
      ...Array.from({ length: 4 }, (_, index) => row(`unclassified-${index}`, "listing_photo")),
      row("unrelated", "listing_photo", "other"),
      ...Array.from({ length: 35 }, (_, index) => row(`photo-${index}`, "listing_photo", "living")),
      row("diagram", "floor_plan_diagram", "diagram"),
    ];

    const selected = selectPropertyImageRows(candidates);

    expect(selected.filter((image) => image.kind === "listing_photo")).toHaveLength(30);
    expect(selected.map((image) => image.id)).toContain("photo-29");
    expect(selected.map((image) => image.id)).not.toContain("unrelated");
    expect(selected.map((image) => image.id)).not.toContain("unclassified-0");
    expect(selected.map((image) => image.id)).toContain("diagram");
  });
});
