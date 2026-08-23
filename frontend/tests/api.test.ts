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
  it("projects the canonical LLM assessment into the gallery API shape", () => {
    expect(projectImageClassifications({
      classification: {
        assessment: { primary_scene: "kitchen" },
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
      classification: { primaryScene: "kitchen" },
      kitchenAssessment: {
        visibility: "visible",
        rating: 4,
        confidence: "high",
        rationale: "Modern flat-panel cabinets and updated appliances are visible.",
      },
    });
  });

  it("keeps an un-refreshed ONNX row visible until the LLM rewrite", () => {
    expect(projectImageClassifications({
      classification: {
        assessment: { predicted_scene: "residential_kitchen", kitchen_score: 0.72 },
      },
    })).toEqual({
      classification: { primaryScene: "residential_kitchen", kitchenProbability: 0.72 },
    });
  });

  it("uses a leftover ONNX shadow only when canonical classification is absent", () => {
    expect(projectImageClassifications({
      classification_shadow: {
        assessment: { predicted_scene: "livingroom", kitchen_score: 0.08 },
      },
    })).toEqual({
      classification: { primaryScene: "livingroom", kitchenProbability: 0.08 },
    });
  });

  it("prefers the LLM canonical scene over a leftover ONNX shadow", () => {
    expect(projectImageClassifications({
      classification: { assessment: { primary_scene: "living" } },
      classification_shadow: {
        assessment: { predicted_scene: "livingroom", kitchen_score: 0.08 },
      },
    })).toEqual({
      classification: { primaryScene: "living" },
    });
  });
});
