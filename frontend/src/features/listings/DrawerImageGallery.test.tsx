import { render, screen, fireEvent } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { DrawerImageGallery } from "./DrawerImageGallery";
import type { PropertyImage } from "./api";

const imgs = [
  { id: "a", url: "http://x/a.webp", width: null, height: null },
  { id: "b", url: "http://x/b.webp", width: null, height: null },
] satisfies PropertyImage[];
const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

it("shows a counter and advances the primary image via next", () => {
  wrap(<DrawerImageGallery images={imgs} loading={false} />);
  expect(screen.getByText("1 / 2")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /next photo/i }));
  expect(screen.getByText("2 / 2")).toBeInTheDocument();
});

it("renders the empty state when there are no photos", () => {
  wrap(<DrawerImageGallery images={[]} loading={false} />);
  expect(screen.getByText(/No photos collected yet/i)).toBeInTheDocument();
});
