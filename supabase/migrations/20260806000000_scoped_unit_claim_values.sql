-- Generated Catalog sync from shared/src/manzil_shared/catalog.py.
-- P3-SC4 separates raw Source claim schemas from scoreable per-Floor-Plan
-- values for the migrated unit-feature tranche. Idempotent on hosted/local DBs.

insert into criteria_catalog
  (key, label, category, domain, fact_scope, value_schema, claim_value_schema, default_options, extraction_hint, requires_tool, refresh_class, escalation_policy, conflict_policy)
values
  ('patio_balcony', 'Patio or balcony', 'unit', 'rent', 'floor_plan', '{"type": "string", "enum": ["confirmed", "advertised_unconfirmed", "none"]}'::jsonb, '{"type": "boolean"}'::jsonb, '[{"match": {"op": "eq", "value": "confirmed"}, "delta": 0.5}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}, {"match": {"op": "eq", "value": "none"}, "delta": 0.0}]'::jsonb, 'True if the unit has a private patio or balcony.', null, 'listing_details', 'decision_relevant', 'standard_ladder'),
  ('private_entry', 'Private entrance', 'unit', 'rent', 'floor_plan', '{"type": "string", "enum": ["confirmed", "advertised_unconfirmed", "none"]}'::jsonb, '{"type": "boolean"}'::jsonb, '[{"match": {"op": "eq", "value": "confirmed"}, "delta": 0.25}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}, {"match": {"op": "eq", "value": "none"}, "delta": 0.0}]'::jsonb, 'True if the unit has its own exterior entrance rather than a shared interior corridor.', null, 'listing_details', 'decision_relevant', 'standard_ladder'),
  ('in_unit_laundry', 'Laundry', 'fittings', 'rent', 'mixed', '{"type": "string", "enum": ["in_unit", "hookups", "on_site", "none", "advertised_unconfirmed"]}'::jsonb, '{"type": "string", "enum": ["in_unit", "hookups", "on_site", "none"]}'::jsonb, '[{"match": {"op": "eq", "value": "in_unit"}, "delta": 0.0}, {"match": {"op": "eq", "value": "hookups"}, "delta": -0.25}, {"match": {"op": "eq", "value": "on_site"}, "delta": -1.0}, {"match": {"op": "eq", "value": "none"}, "delta": -2.0}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}]'::jsonb, 'in_unit = washer/dryer inside the unit; hookups = connections only; on_site = shared laundry room/facilities; none otherwise.', null, 'listing_details', 'decision_relevant', 'standard_ladder'),
  ('parking', 'Parking', 'unit', 'rent', 'mixed', '{"type": "string", "enum": ["garage", "carport", "covered", "dedicated_lot", "street_only", "none", "advertised_unconfirmed"]}'::jsonb, '{"type": "string", "enum": ["garage", "carport", "covered", "dedicated_lot", "street_only", "none"]}'::jsonb, '[{"match": {"op": "eq", "value": "garage"}, "delta": 0.5}, {"match": {"op": "eq", "value": "carport"}, "delta": 0.25}, {"match": {"op": "eq", "value": "covered"}, "delta": 0.25}, {"match": {"op": "eq", "value": "dedicated_lot"}, "delta": 0.0}, {"match": {"op": "eq", "value": "street_only"}, "delta": -0.5}, {"match": {"op": "eq", "value": "none"}, "delta": -1.0}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}]'::jsonb, 'Best parking included or available with the unit: garage, carport, covered, dedicated_lot (assigned or off-street lot), street_only, or none.', null, 'listing_details', 'decision_relevant', 'standard_ladder'),
  ('cooling', 'Cooling', 'fittings', 'rent', 'floor_plan', '{"type": "string", "enum": ["central", "window_units", "none", "advertised_unconfirmed"]}'::jsonb, '{"type": "string", "enum": ["central", "window_units", "none"]}'::jsonb, '[{"match": {"op": "eq", "value": "central"}, "delta": 0.5}, {"match": {"op": "eq", "value": "window_units"}, "delta": 0.0}, {"match": {"op": "eq", "value": "none"}, "delta": -1.0}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}]'::jsonb, 'central = central air conditioning; window_units = window/wall units provided or explicitly permitted; none otherwise.', null, 'listing_details', 'decision_relevant', 'standard_ladder'),
  ('dishwasher', 'Dishwasher', 'fittings', 'rent', 'floor_plan', '{"type": "string", "enum": ["confirmed", "advertised_unconfirmed", "none"]}'::jsonb, '{"type": "boolean"}'::jsonb, '[{"match": {"op": "eq", "value": "confirmed"}, "delta": 0.25}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}, {"match": {"op": "eq", "value": "none"}, "delta": 0.0}]'::jsonb, 'True if the unit includes a dishwasher.', null, 'listing_details', 'decision_relevant', 'standard_ladder')
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
