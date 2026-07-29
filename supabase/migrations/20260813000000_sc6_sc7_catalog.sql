-- Generated Catalog sync from shared/src/manzil_shared/catalog.py.
-- P3-SC6/SC7 objective unit-feature and flooring tranches; idempotent on hosted/local databases.

insert into criteria_catalog
  (key, label, category, domain, fact_scope, value_schema, claim_value_schema, default_options, extraction_hint, requires_tool, refresh_class, escalation_policy, conflict_policy)
values
  ('flooring_materials', 'Flooring materials', 'fittings', 'rent', 'mixed', '{"type": "array", "items": {"type": "string", "enum": ["carpet", "hardwood", "engineered_wood", "laminate", "vinyl", "tile", "concrete", "other"]}, "minItems": 1, "uniqueItems": true}'::jsonb, null, '[{"match": {"op": "contains_any", "value": ["carpet", "hardwood", "engineered_wood", "laminate", "vinyl", "tile", "concrete", "other"]}, "delta": 0.0}]'::jsonb, 'Objective flooring materials inside the unit. Use only carpet, hardwood, engineered_wood, laminate, vinyl, tile, concrete, or other; include every explicitly stated material for the concrete target. Do not infer material from appearance or use this field for condition/quality.', null, 'listing_details', 'decision_relevant', 'standard_ladder'),
  ('walk_in_closets', 'Walk-in closets', 'fittings', 'rent', 'floor_plan', '{"type": "string", "enum": ["confirmed", "advertised_unconfirmed", "none"]}'::jsonb, '{"type": "boolean"}'::jsonb, '[{"match": {"op": "eq", "value": "confirmed"}, "delta": 0.25}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}, {"match": {"op": "eq", "value": "none"}, "delta": 0.0}]'::jsonb, 'True only for an explicitly stated walk-in closet inside the unit; large or ample closets alone are not sufficient.', null, 'listing_details', 'available_sources_only', 'verified_positive_preferred'),
  ('pantry', 'Pantry', 'fittings', 'rent', 'floor_plan', '{"type": "string", "enum": ["confirmed", "advertised_unconfirmed", "none"]}'::jsonb, '{"type": "boolean"}'::jsonb, '[{"match": {"op": "eq", "value": "confirmed"}, "delta": 0.25}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}, {"match": {"op": "eq", "value": "none"}, "delta": 0.0}]'::jsonb, 'True only when the unit explicitly includes a pantry; cabinet or walk-in pantry details may remain in the evidence.', null, 'listing_details', 'available_sources_only', 'verified_positive_preferred'),
  ('disposal', 'Garbage disposal', 'fittings', 'rent', 'floor_plan', '{"type": "string", "enum": ["confirmed", "advertised_unconfirmed", "none"]}'::jsonb, '{"type": "boolean"}'::jsonb, '[{"match": {"op": "eq", "value": "confirmed"}, "delta": 0.25}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}, {"match": {"op": "eq", "value": "none"}, "delta": 0.0}]'::jsonb, 'True only when the unit explicitly includes a kitchen garbage disposal.', null, 'listing_details', 'available_sources_only', 'verified_positive_preferred'),
  ('fireplace', 'Fireplace', 'fittings', 'rent', 'floor_plan', '{"type": "string", "enum": ["confirmed", "advertised_unconfirmed", "none"]}'::jsonb, '{"type": "boolean"}'::jsonb, '[{"match": {"op": "eq", "value": "confirmed"}, "delta": 0.25}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}, {"match": {"op": "eq", "value": "none"}, "delta": 0.0}]'::jsonb, 'True only for a fireplace inside the unit, not a clubhouse, lounge, outdoor fireplace, or fire pit.', null, 'listing_details', 'available_sources_only', 'verified_positive_preferred'),
  ('ceiling_fans', 'Ceiling fans', 'fittings', 'rent', 'floor_plan', '{"type": "string", "enum": ["confirmed", "advertised_unconfirmed", "none"]}'::jsonb, '{"type": "boolean"}'::jsonb, '[{"match": {"op": "eq", "value": "confirmed"}, "delta": 0.25}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}, {"match": {"op": "eq", "value": "none"}, "delta": 0.0}]'::jsonb, 'True only when the unit explicitly includes one or more ceiling fans.', null, 'listing_details', 'available_sources_only', 'verified_positive_preferred'),
  ('stainless_steel_appliances', 'Stainless steel appliances', 'fittings', 'rent', 'floor_plan', '{"type": "string", "enum": ["confirmed", "advertised_unconfirmed", "none"]}'::jsonb, '{"type": "boolean"}'::jsonb, '[{"match": {"op": "eq", "value": "confirmed"}, "delta": 0.25}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}, {"match": {"op": "eq", "value": "none"}, "delta": 0.0}]'::jsonb, 'True only when the unit''s appliance finish is explicitly stainless steel; this does not assert appliance age, condition, or quality.', null, 'listing_details', 'available_sources_only', 'verified_positive_preferred')
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
