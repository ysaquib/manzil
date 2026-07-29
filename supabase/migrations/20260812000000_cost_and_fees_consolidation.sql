-- P3-SC8 estimated move-in cost + the consolidated Cost & fees surface
-- (DESIGN §9.5, §20 2026-07-28).
--
-- Three things land here:
--
-- 1. fee_checklist gains the per-charge decisions the consolidated section
--    edits.  `counted` is the human's explicit include/exclude decision for a
--    monthly slot (NULL = machine default: counted when an amount is known).
--    `required` and `refundable` are tri-state on purpose — NULL means the
--    Source never said, which is exactly what drives the P3-SC8 Incomplete
--    badge; they must never be read as "false".  `credited_amount` is the part
--    of a one-time charge applied to first month's rent, so only the
--    non-credited remainder becomes cash at move-in.
-- 2. scores/hunt_listings gain move_in_components, the P3-SC8 sibling of
--    all_in_components: display metadata beside the pinned breakdown, per plan
--    on scores and the display plan's copy on hunt_listings.
-- 3. The estimated_move_in_cost Catalog row (generated from
--    shared/src/manzil_shared/catalog.py).

alter table fee_checklist add column counted boolean;
alter table fee_checklist add column required boolean;
alter table fee_checklist add column refundable boolean;
alter table fee_checklist add column credited_amount numeric(10, 2)
    check (credited_amount is null or credited_amount >= 0);

comment on column fee_checklist.counted is
    'Human include/exclude decision for the all-in composition; NULL = machine default.';
comment on column fee_checklist.required is
    'Required to move in. NULL = the Source never said — drives the P3-SC8 Incomplete badge.';
comment on column fee_checklist.refundable is
    'NULL = unknown refundability; never read as non-refundable.';
comment on column fee_checklist.credited_amount is
    'Portion credited to first month rent; only the remainder is cash at move-in.';

alter table scores add column move_in_components jsonb;
alter table hunt_listings add column move_in_components jsonb;

-- Catalog sync: the one new P3-SC8 entry (idempotent; other rows untouched).
insert into criteria_catalog
  (key, label, category, domain, fact_scope, value_schema, claim_value_schema, default_options, extraction_hint, requires_tool, refresh_class, escalation_policy, conflict_policy)
values
  ('estimated_move_in_cost', 'Estimated move-in cost', 'cost', 'rent', 'composed', '{"type": "number", "minimum": 0}'::jsonb, null, '[{"match": {"op": "lt", "value": 2500}, "delta": 1.0}, {"match": {"op": "range", "value": [2500, 4000]}, "delta": 0.5}, {"match": {"op": "range", "value": [4000, 5500]}, "delta": 0.0}, {"match": {"op": "range", "value": [5500, 7000]}, "delta": -0.5}, {"match": {"op": "gt", "value": 7000}, "delta": -1.0}]'::jsonb, 'Composed by the pipeline (P3-SC8, DESIGN §9.5) from the first month''s all-in, the security deposit, required one-time fees and prepaids — never extracted directly from the page. A missing required component leaves it unknown.', null, 'pricing', 'decision_relevant', 'standard_ladder')
on conflict (key) do update set
  label = excluded.label,
  category = excluded.category,
  domain = excluded.domain,
  fact_scope = excluded.fact_scope,
  value_schema = excluded.value_schema,
  claim_value_schema = excluded.claim_value_schema,
  default_options = excluded.default_options,
  extraction_hint = excluded.extraction_hint,
  requires_tool = excluded.requires_tool,
  refresh_class = excluded.refresh_class,
  escalation_policy = excluded.escalation_policy,
  conflict_policy = excluded.conflict_policy;
