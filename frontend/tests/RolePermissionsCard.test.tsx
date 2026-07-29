// The role card renders for every role, Owner included (P3-16). Its job is to
// answer "why can't I do that?" in the vocabulary the app actually uses.
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RolePermissionsCard } from "../src/features/collaboration/RolePermissionsCard";
import { renderWithProviders } from "./testUtils";

describe("RolePermissionsCard", () => {
  it("names the mechanism — role and permissions — for an Owner", () => {
    renderWithProviders(<RolePermissionsCard role="owner" />);

    expect(screen.getByRole("heading", { name: "Your role and permissions" })).toBeInTheDocument();
    expect(screen.getByText(/Your role in this hunt is/)).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText(/A role is a bundle of permissions/)).toBeInTheDocument();
    // The Owner withholds nothing, and says so rather than showing an empty list.
    expect(screen.getByText(/highest role in a hunt/)).toBeInTheDocument();
  });

  it("shows a Member what is withheld and who to ask", () => {
    renderWithProviders(<RolePermissionsCard role="member" ownerName="Yusuf" />);

    expect(screen.getByText("Not permitted by this role")).toBeInTheDocument();
    expect(screen.getByText("Edit the Rubric")).toBeInTheDocument();
    expect(screen.getByText(/Ask Yusuf to change your role/)).toBeInTheDocument();
  });

  it("falls back to 'the Owner' when the owner has no display name", () => {
    renderWithProviders(<RolePermissionsCard role="curator" />);
    expect(screen.getByText(/Ask the Owner to change your role/)).toBeInTheDocument();
  });

  it("labels the permitted group with the reader's own role", () => {
    renderWithProviders(<RolePermissionsCard role="curator" />);
    expect(screen.getByText("The Curator role permits")).toBeInTheDocument();
  });
});
