import type { HuntContributor, HuntMember } from "./api";
import { memberColor } from "./memberColors";

const CURRENT_MEMBER_FALLBACK = "Member";
const UNKNOWN_CONTRIBUTOR_FALLBACK = "Former User";
const FORMER_COLOR = "var(--mantine-color-gray-5)";

type ContributorIdentity = Pick<
  HuntContributor,
  "user_id" | "display_name" | "color" | "is_former"
>;

function isFormer(
  contributor: ContributorIdentity | HuntMember | null | undefined,
): contributor is ContributorIdentity {
  return Boolean(contributor && "is_former" in contributor && contributor.is_former);
}

export function contributorDisplayName(
  contributor: ContributorIdentity | HuntMember | null | undefined,
): string {
  if (!contributor) return UNKNOWN_CONTRIBUTOR_FALLBACK;
  const name = contributor.display_name?.trim() || CURRENT_MEMBER_FALLBACK;
  if (!isFormer(contributor)) return name;
  // Old tombstones may predate the removal-time name snapshot. Never turn
  // their generic fallback into the misleading "Former User (Member)".
  return name === "Member" || name === "Unknown" || name === "Former User"
    ? UNKNOWN_CONTRIBUTOR_FALLBACK
    : `Former User (${name})`;
}

export function contributorColor(
  contributor: ContributorIdentity | HuntMember | null | undefined,
): string {
  return !contributor || isFormer(contributor)
    ? FORMER_COLOR
    : memberColor(contributor.color ?? null);
}

/** Hunt-visible name for attribution tooltips — never a raw auth user id. */
export function memberDisplayName(
  contributors: (ContributorIdentity | HuntMember)[],
  userId: string | null | undefined,
): string | undefined {
  if (!userId) return undefined;
  const contributor = contributors.find((row) => row.user_id === userId);
  return contributorDisplayName(contributor);
}

export function memberDisplayNameMap(
  contributors: (ContributorIdentity | HuntMember)[],
): Map<string, string> {
  return new Map(
    contributors.map((contributor) => [
      contributor.user_id,
      memberDisplayName(contributors, contributor.user_id)!,
    ]),
  );
}
