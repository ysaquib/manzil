import { render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { DrawerImageGallery } from "../src/features/listings/DrawerImageGallery";
import type { PropertyImage } from "../src/features/listings/api";

const imgs = [
  { id: "a", url: "http://x/a.webp", width: null, height: null },
  { id: "b", url: "http://x/b.webp", width: null, height: null },
] satisfies PropertyImage[];
const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

it("renders a carousel slide per photo, the counter, and the thumbnail strip", () => {
  wrap(<DrawerImageGallery images={imgs} loading={false} />);
  expect(screen.getByText("1 / 2")).toBeInTheDocument();
  // one primary "open photo" button per image, plus a thumbnail per image
  expect(screen.getAllByRole("button", { name: /open photo/i })).toHaveLength(2);
  expect(screen.getAllByRole("button", { name: /show photo/i })).toHaveLength(2);
  // carousel controls are present for multi-image galleries
  expect(screen.getByRole("button", { name: /next photo/i })).toBeInTheDocument();
});

it("renders the empty state when there are no photos", () => {
  wrap(<DrawerImageGallery images={[]} loading={false} />);
  expect(screen.getByText(/No photos collected yet/i)).toBeInTheDocument();
});

it("shows the canonical ONNX scene without exposing kitchen probability", () => {
  const classified = [{
    id: "classified",
    url: "http://x/classified.webp",
    width: null,
    height: null,
    classification: { primaryScene: "residential_kitchen", kitchenProbability: 0.72 },
    kitchenAssessment: {
      visibility: "visible",
      rating: 4,
      confidence: "high",
      rationale: "Modern flat-panel cabinets and updated appliances are visible.",
    },
  }] satisfies PropertyImage[];

  wrap(<DrawerImageGallery images={classified} loading={false} />);

  expect(screen.getByText("residential kitchen")).toBeInTheDocument();
  expect(screen.queryByText(/Kitchen probability/)).not.toBeInTheDocument();
  expect(screen.getByText("Kitchen assessment")).toBeInTheDocument();
  expect(screen.getByText("Rated 4/5 · high confidence")).toBeInTheDocument();
  expect(screen.getByText("Modern flat-panel cabinets and updated appliances are visible.")).toBeInTheDocument();
});
