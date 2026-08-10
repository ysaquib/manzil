import { describe, expect, it } from "vitest";

import {
  invitationDeliveryPollInterval,
  type Invite,
} from "../src/features/invites/api";

function invite(status: Invite["delivery_status"]): Invite {
  return {
    id: "invite-1",
    hunt_id: "hunt-1",
    email: "friend@example.com",
    role_granted: "member",
    expires_at: "2026-08-17T00:00:00Z",
    link: "https://manzil.example/invite/token",
    delivery_status: status,
  };
}

describe("invitationDeliveryPollInterval", () => {
  it.each(["queued", "sending", "sent", "delayed"] as const)(
    "polls while a delivery is %s",
    (status) => expect(invitationDeliveryPollInterval([invite(status)])).toBe(5_000),
  );

  it.each(
    ["delivered", "failed", "bounced", "suppressed", "complained", "disabled", "cancelled"] as const,
  )(
    "stops after a delivery is %s",
    (status) => expect(invitationDeliveryPollInterval([invite(status)])).toBe(false),
  );
});
