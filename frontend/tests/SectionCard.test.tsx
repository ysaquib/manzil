import { render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { SectionCard } from "../src/components/SectionCard";

const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

it("renders a titled card with an optional hint and its children", () => {
  wrap(
    <SectionCard title="Why this score" hint="13 criteria">
      <p>body</p>
    </SectionCard>,
  );
  expect(screen.getByRole("heading", { name: "Why this score" })).toBeInTheDocument();
  expect(screen.getByText("13 criteria")).toBeInTheDocument();
  expect(screen.getByText("body")).toBeInTheDocument();
});
