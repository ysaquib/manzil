-- VC-8 — the Unit Group roll-up (DESIGN §9.7, plan §6).
--
-- A tour rates doors; the Overview compares Unit Groups. This view is the whole
-- of that translation, and every step of it is a decision the plan already
-- ruled on:
--
--   1. A unit's score is the mean **across members** of each member's own
--      unit-scope Impression ratings. Per member first, then across them, so
--      somebody who rated ten items does not outvote somebody who rated two.
--      Building-scope Impressions are excluded (plan Q4): they are identical on
--      every row of that Property, so including them would compress the
--      differences between rows without adding information.
--   2. **Same door toured twice, latest visit wins.** A second showing is a
--      correction; best-of across time would let a rosy first impression
--      outrank the careful second look.
--   3. **Several doors in one group, the best.** Same shape as the Display
--      Floor Plan rule (§9.4), so the table keeps its existing "best of what's
--      here" semantics.
--   4. **A described unit matching no advertised group gets no row.** Minting a
--      Unit Group would contradict §3 — groups are derived from a Property's
--      Floor Plans, never invented. It stays visible on the Visit and in the
--      drawer's Visits list. Showing nothing beats inventing a row.
--
-- A view rather than a projection until it measurably hurts: correctness first,
-- and `all_in_components` is the precedent for promoting it later.

-- Which entries count as a unit-scope Impression, resolving custom items
-- against `visit_custom_items` and template items at the Visit's frozen
-- version — the same two-source shape lookup the write path uses.
create view visit_unit_impressions with (security_invoker = true) as
select
    e.visit_id,
    e.visit_unit_id,
    e.owner_user_id,
    (e.value #>> '{}')::numeric as rating
from current_visit_entries e
join visits v on v.id = e.visit_id
left join visit_template_items t
    on not e.is_custom and t.key = e.item_key and t.version = v.template_version
left join visit_custom_items c
    on e.is_custom and c.id::text = e.item_key and c.visit_id = e.visit_id
where e.visit_unit_id is not null
  and e.owner_user_id is not null
  and e.value is not null
  -- jsonb numbers only: a rating that is not a number is not a rating.
  and jsonb_typeof(e.value) = 'number'
  and coalesce(t.kind, c.kind) = 'impression'
  and coalesce(t.scope, c.scope) = 'unit';

comment on view visit_unit_impressions is
    'Unit-scope Impression ratings, one row per (visit unit, member, item). '
    'Feeds visit_unit_group_scores (VC-8).';

create view visit_unit_group_scores with (security_invoker = true) as
with member_means as (
    -- Each member's own opinion of a door, as one number.
    select visit_unit_id, owner_user_id, avg(rating) as member_score
    from visit_unit_impressions
    group by visit_unit_id, owner_user_id
),
unit_scores as (
    select visit_unit_id, avg(member_score) as unit_score, count(*) as rater_count
    from member_means
    group by visit_unit_id
),
toured as (
    select
        hl.id as hunt_listing_id,
        u.unit_group_key,
        u.id as visit_unit_id,
        u.label,
        v.id as visit_id,
        -- A tour's date is when it happened, falling back to when it was meant
        -- to happen and then to when it was written down.
        coalesce(v.started_at, v.scheduled_for, v.created_at) as visited_at,
        s.unit_score,
        s.rater_count
    from visit_units u
    join visits v on v.id = u.visit_id
    join hunt_listings hl
        on hl.hunt_id = v.hunt_id
       and hl.property_id = v.property_id
    join unit_scores s on s.visit_unit_id = u.id
    -- A cancelled tour is not evidence about the property.
    where v.cancelled_at is null
      -- Rule 4: the Property must actually advertise this Unit Group.
      and private.listing_has_unit_group(hl.id, u.unit_group_key)
),
-- Rule 2: one row per door, from its most recent tour. A door's identity across
-- Visits is its human-typed label within the Listing — there is no unit
-- inventory to key on, which is exactly why §18's deferral is intact.
latest_per_door as (
    select distinct on (hunt_listing_id, lower(label))
        hunt_listing_id, unit_group_key, visit_unit_id, visit_id, visited_at, unit_score, rater_count
    from toured
    order by hunt_listing_id, lower(label), visited_at desc, visit_unit_id desc
)
-- Rule 3: the best door in the group represents it.
select distinct on (hunt_listing_id, unit_group_key)
    hunt_listing_id,
    unit_group_key,
    round(unit_score, 2) as score,
    visit_unit_id as best_visit_unit_id,
    visit_id as best_visit_id,
    visited_at as best_visited_at,
    rater_count,
    -- How many doors in this group were toured, so the cell can say "best of N"
    -- with the same ×N affordance the score cell already uses.
    (
        select count(*) from latest_per_door peer
        where peer.hunt_listing_id = latest_per_door.hunt_listing_id
          and peer.unit_group_key = latest_per_door.unit_group_key
    ) as unit_count
from latest_per_door
order by hunt_listing_id, unit_group_key, unit_score desc, visited_at desc;

comment on view visit_unit_group_scores is
    'Visit score per (hunt_listing_id, unit_group_key) — DESIGN §9.7, VC-8. '
    'Latest tour per door, then the best door in the group; a described unit '
    'matching no advertised Unit Group produces no row. Never merged with the '
    'Rubric score: this is a human judgement shown beside Fit, never inside it.';
