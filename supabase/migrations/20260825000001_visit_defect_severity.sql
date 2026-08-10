-- VC-10 — defect severity gets a vocabulary (DESIGN §9.7, §20).
--
-- `severity smallint check (severity between 1 and 5)` rendered as five stars.
-- Two problems, one of them in the data rather than the control: nothing
-- anywhere said what a 3 meant, so two members walking the same flat were
-- writing different scales into the same column; and stars read as *quality*
-- everywhere else in this app, so on a defect more stars looked like better
-- news.
--
-- Four named levels, each with its own band of the existing status ramp:
--
--     noted        sage    does not affect day to day, but worth writing down
--     minor        ochre   affects it; you can live with it
--     major        clay    costs money or comfort
--     dealbreaker  brick   you would not sign
--
-- Four rather than three because the ramp is then evenly spaced: two levels you
-- would accept and two you would negotiate over, instead of one bucket doing
-- the work of "cosmetic" and "annoying" at once.
--
-- Still nullable. **Unrated stays a real state** — a defect promoted from a
-- failed Check starts unrated, and on a tour you are still walking that is the
-- truth rather than a missing value to be defaulted away.

create type visit_defect_severity as enum ('noted', 'minor', 'major', 'dealbreaker');

comment on type visit_defect_severity is
    'How badly a Visit defect matters (VC-10). Ordered least to worst; null is '
    'unrated, which is a real state and not a missing value.';

-- Add, backfill, drop, rename — rather than an in-place type change, so the
-- mapping below is visible in the migration that performed it.
alter table visit_defects
    add column severity_level visit_defect_severity;

-- 1-5 collapses to four bands. 3 and 4 both land on `major`: the old scale's
-- middle was where "costs something" lived, and splitting it would invent a
-- distinction the person tapping a star never made.
update visit_defects
set severity_level = case severity
        when 1 then 'noted'::visit_defect_severity
        when 2 then 'minor'::visit_defect_severity
        when 3 then 'major'::visit_defect_severity
        when 4 then 'major'::visit_defect_severity
        when 5 then 'dealbreaker'::visit_defect_severity
    end
where severity is not null;

alter table visit_defects drop column severity;
alter table visit_defects rename column severity_level to severity;

comment on column visit_defects.severity is
    'Named severity (VC-10). Null means unrated, which a promoted defect starts as.';
