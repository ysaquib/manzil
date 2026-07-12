import { describe, expect, it } from "vitest";

import { invitationLinkForCurrentOrigin } from "./api";

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
