import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { HuntMember } from "../src/features/collaboration/api";
import type { PresentMember } from "../src/features/visits/usePresence";
import {
  VisitPresence,
  initialsFor,
  presenceSentence,
} from "../src/features/visits/VisitPresence";
import { renderWithProviders } from "./testUtils";

const members: HuntMember[] = [
  { hunt_id: "h1", user_id: "u1", role: "owner", color: "plum", display_name: "Yusuf" },
  { hunt_id: "h1", user_id: "u2", role: "member", color: "ochre", display_name: "Sana" },
  { hunt_id: "h1", user_id: "u3", role: "member", color: "brick", display_name: "Dan" },
];

function present(userId: string, sectionKey: string | null, onlineAt = 1): PresentMember {
  return { userId, sectionKey, onlineAt };
}

const nameOf = (userId: string) =>
  members.find((member) => member.user_id === userId)?.display_name ?? "Someone";

describe("presenceSentence", () => {
  it("says nothing when nobody else is here — silence is the common case", () => {
    expect(presenceSentence([], nameOf)).toBeNull();
  });

  it("names the section for a single person, because that is the useful part", () => {
    expect(presenceSentence([present("u2", "kitchen")], nameOf)).toBe("Sana is in Kitchen");
  });

  it("falls back to 'here' when they have not opened a section", () => {
    expect(presenceSentence([present("u2", null)], nameOf)).toBe("Sana is here");
  });

  it("names both when two are here", () => {
    expect(presenceSentence([present("u2", "kitchen"), present("u3", "noise")], nameOf)).toBe(
      "Sana and Dan are here",
    );
  });

  it("counts rather than listing beyond two — the strip has to fit a phone", () => {
    expect(
      presenceSentence(
        [present("u2", null), present("u3", null), present("u1", null)],
        nameOf,
      ),
    ).toBe("3 others are here");
  });

  it("uses the section's human title, not its key", () => {
    expect(presenceSentence([present("u2", "verdict_unit")], nameOf)).toBe(
      "Sana is in Verdict — this unit",
    );
  });
});

describe("initialsFor", () => {
  it("takes the first letter, uppercased", () => {
    expect(initialsFor("sana")).toBe("S");
  });

  it("degrades to a question mark rather than rendering nothing", () => {
    expect(initialsFor(null)).toBe("?");
    expect(initialsFor("   ")).toBe("?");
  });
});

describe("VisitPresence", () => {
  it("renders nothing at all when nobody else is here", () => {
    renderWithProviders(<VisitPresence present={[]} members={members} />);
    // No bar, no avatars — presence is silent by default rather than showing an
    // empty strip. (MantineProvider injects a <style> tag, so the container is
    // never literally empty; assert on what a reader would see.)
    expect(screen.queryByText(/here|is in/)).not.toBeInTheDocument();
    expect(document.querySelectorAll(".mantine-Avatar-root")).toHaveLength(0);
  });

  it("shows an avatar per person plus the sentence", () => {
    renderWithProviders(
      <VisitPresence present={[present("u2", "kitchen"), present("u3", null)]} members={members} />,
    );
    expect(screen.getByText("Sana and Dan are here")).toBeInTheDocument();
    expect(screen.getByText("S")).toBeInTheDocument();
    expect(screen.getByText("D")).toBeInTheDocument();
  });

  it("still renders someone who is present but not a known member", () => {
    // Presence can arrive slightly before the member list does; showing a
    // placeholder beats blanking the row.
    renderWithProviders(<VisitPresence present={[present("ghost", null)]} members={members} />);
    expect(screen.getByText("Someone is here")).toBeInTheDocument();
  });
});
