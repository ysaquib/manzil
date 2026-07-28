import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "./testUtils";
import type { PropertyImage } from "../src/features/listings/api";
import {
  UnmatchedDiagrams,
  unmatchedDiagrams,
} from "../src/features/listings/UnmatchedDiagrams";

function image(over: Partial<PropertyImage> & { id: string }): PropertyImage {
  return {
    url: `https://signed.test/${over.id}.webp`,
    width: 2048,
    height: 1400,
    kind: "floor_plan_diagram",
    floorPlanAssociations: [],
    ...over,
  };
}

const ambiguous = image({ id: "amb-1" });
const linked = image({ id: "linked", floorPlanAssociations: ["plan-a"] });
const photo = image({ id: "photo", kind: "listing_photo" });

describe("unmatchedDiagrams", () => {
  it("keeps only diagrams with no current association", () => {
    expect(unmatchedDiagrams([ambiguous, linked, photo]).map((i) => i.id)).toEqual(["amb-1"]);
  });

  it("never treats a Property photo as a diagram", () => {
    expect(unmatchedDiagrams([photo])).toEqual([]);
  });
});

describe("UnmatchedDiagrams", () => {
  it("renders nothing when every diagram found a plan", () => {
    // An empty "unmatched" heading would imply a problem where there is none.
    renderWithProviders(<UnmatchedDiagrams images={[linked, photo]} />);
    expect(screen.queryByText(/could not be tied to a specific plan/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("says why the diagrams are here rather than on a plan", () => {
    renderWithProviders(<UnmatchedDiagrams images={[ambiguous, linked]} />);
    expect(
      screen.getByText(/could not be tied to a specific plan/),
    ).toBeInTheDocument();
    expect(screen.getByText(/rather than attaching to every floor plan/)).toBeInTheDocument();
  });

  it("opens a diagram in the lightbox", async () => {
    const user = userEvent.setup();
    renderWithProviders(<UnmatchedDiagrams images={[ambiguous, image({ id: "amb-2" })]} />);

    await user.click(
      screen.getByRole("button", { name: "Open unmatched floor plan diagram 1 of 2" }),
    );
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
