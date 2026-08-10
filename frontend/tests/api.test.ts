import { describe, expect, it } from "vitest";

import { invitationLinkForCurrentOrigin } from "../src/features/invites/api";
import { projectImageClassifications } from "../src/features/listings/api";

describe("invitationLinkForCurrentOrigin", () => {
  it("keeps the join path but uses the browser's authenticated origin", () => {
    expect(
      invitationLinkForCurrentOrigin(
        "https://configured.example/join/token-123",
        "https://app.example",
      ),
    ).toBe("https://app.example/join/token-123");
  });
});

describe("projectImageClassifications", () => {
  it("projects the canonical ONNX assessment into the gallery API shape", () => {
    expect(projectImageClassifications({
      classification: {
        assessment: { predicted_scene: "residential_kitchen", kitchen_score: 0.72 },
      },
      kitchen_quality: {
        assessment: {
          visibility: "visible",
          rating: 4,
          confidence: "high",
          rationale: "Modern flat-panel cabinets and updated appliances are visible.",
        },
      },
    })).toEqual({
      classification: { primaryScene: "residential_kitchen", kitchenProbability: 0.72 },
      kitchenAssessment: {
        visibility: "visible",
        rating: 4,
        confidence: "high",
        rationale: "Modern flat-panel cabinets and updated appliances are visible.",
      },
    });
  });

  it("uses a rollout shadow until the backend promotes it on refresh", () => {
    expect(projectImageClassifications({
      classification: { assessment: { primary_scene: "living" } },
      classification_shadow: {
        assessment: { predicted_scene: "livingroom", kitchen_score: 0.08 },
      },
    })).toEqual({
      classification: { primaryScene: "livingroom", kitchenProbability: 0.08 },
    });
  });

  it("does not present a legacy LLM-only assessment as canonical", () => {
    expect(projectImageClassifications({
      classification: { assessment: { primary_scene: "living" } },
    })).toEqual({ classification: undefined });
  });
});
