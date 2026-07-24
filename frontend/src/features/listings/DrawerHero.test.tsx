import { render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { DrawerHero } from "./DrawerHero";

const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

it("renders identity, the score with its label, all-in, and beds/baths", () => {
  wrap(<DrawerHero name="Maple Court" address="1420 Alder St" images={[]} imagesLoading={false}
    score={12.5} allIn={1845} estimated={210} bedsBaths="Studio · 1 bath" />);
  expect(screen.getByRole("heading", { name: "Maple Court" })).toBeInTheDocument();
  expect(screen.getByText("1420 Alder St")).toBeInTheDocument();
  expect(screen.getByText("12.5")).toBeInTheDocument();
  expect(screen.getByText("Exceptional Match")).toBeInTheDocument();
  expect(screen.getByText("$1,845")).toBeInTheDocument();
  expect(screen.getByText(/210 estimated/)).toBeInTheDocument();
  expect(screen.getByText("Studio · 1 bath")).toBeInTheDocument();
});

it("shows a not-scored tile when score is null", () => {
  wrap(<DrawerHero name="X" address="Y" images={[]} imagesLoading={false}
    score={null} allIn={null} estimated={null} bedsBaths={null} />);
  expect(screen.getByText(/Not scored yet/i)).toBeInTheDocument();
});
