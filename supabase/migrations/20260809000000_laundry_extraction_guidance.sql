-- Generated Catalog sync from shared/src/manzil_shared/catalog.py.
-- Clarify mutually exclusive laundry extraction semantics after the Homestead Commons regression. Idempotent on hosted/local DBs.

insert into criteria_catalog
  (key, label, category, domain, fact_scope, value_schema, claim_value_schema, default_options, extraction_hint, requires_tool, refresh_class, escalation_policy, conflict_policy)
values
  ('in_unit_laundry', 'Laundry', 'fittings', 'rent', 'mixed', '{"type": "string", "enum": ["in_unit", "hookups", "on_site", "none", "advertised_unconfirmed"]}'::jsonb, '{"type": "string", "enum": ["in_unit", "hookups", "on_site", "none"]}'::jsonb, '[{"match": {"op": "eq", "value": "in_unit"}, "delta": 0.0}, {"match": {"op": "eq", "value": "hookups"}, "delta": -0.25}, {"match": {"op": "eq", "value": "on_site"}, "delta": -1.0}, {"match": {"op": "eq", "value": "none"}, "delta": -2.0}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}]'::jsonb, 'in_unit = washer/dryer inside the unit; hookups = connections only; on_site = shared laundry room/facilities; none = the page explicitly states that no laundry option of any kind is available. A statement that in-unit laundry is unavailable is not `none` when hookups or shared facilities are stated; emit the best available mode once per concrete target.', null, 'listing_details', 'decision_relevant', 'standard_ladder')
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
