import type { HuntMember } from "./api";

const FALLBACK = "Member";

/** Hunt-visible name for attribution tooltips — never a raw auth user id. */
export function memberDisplayName(
  members: HuntMember[],
  userId: string | null | undefined,
): string | undefined {
  if (!userId) return undefined;
  const member = members.find((row) => row.user_id === userId);
  const name = member?.display_name?.trim();
  return name || FALLBACK;
}

export function memberDisplayNameMap(members: HuntMember[]): Map<string, string> {
  return new Map(
    members.map((member) => [member.user_id, memberDisplayName(members, member.user_id)!]),
  );
}
