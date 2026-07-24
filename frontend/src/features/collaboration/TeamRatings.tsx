import { useRatings, type HuntMember } from "./api";
import { memberColor } from "./memberColors";
import { StarRating } from "./StarRating";
import classes from "./TeamRatings.module.css";

export function TeamRatings({
  listingId,
  unitGroupKey,
  members,
}: {
  listingId: string;
  unitGroupKey: string;
  members: HuntMember[];
  currentUserId?: string;
}) {
  const { data: ratings = [] } = useRatings(listingId);
  const byUser = new Map(
    ratings
      .filter((r) => r.unit_group_key === unitGroupKey)
      .map((r) => [r.user_id, r.rating] as const),
  );
  const present = members
    .map((m) => byUser.get(m.user_id))
    .filter((v): v is number => v != null);
  const avg = present.length ? present.reduce((a, b) => a + b, 0) / present.length : null;
  const initials = (name: string | null) => (name ?? "?").trim().charAt(0).toUpperCase() || "?";

  return (
    <div className={classes.team}>
      <div className={classes.head}>
        <span>The team</span>
        {avg != null && (
          <span className={classes.avg}>
            avg {avg.toFixed(1)} · {present.length} of {members.length} rated
          </span>
        )}
      </div>
      {members.map((m) => {
        const r = byUser.get(m.user_id);
        return (
          <div className={classes.rater} key={m.user_id}>
            <span className={classes.av} style={{ background: memberColor(m.color) }}>
              {initials(m.display_name)}
            </span>
            <span className={classes.name}>{m.display_name ?? "Member"}</span>
            {r != null ? (
              <>
                <span className={classes.rstars}>
                  <StarRating value={r} />
                </span>
                <span className={classes.val}>{r.toFixed(1)}</span>
              </>
            ) : (
              <span className={classes.none}>Not rated yet</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
