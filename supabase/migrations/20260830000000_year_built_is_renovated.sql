-- Generated Catalog sync from shared/src/manzil_shared/catalog.py.
-- P3-SC3 first Property/Unit type tranche; idempotent on hosted and local databases.

insert into criteria_catalog
  (key, label, category, domain, fact_scope, value_schema, claim_value_schema, default_options, extraction_hint, requires_tool, refresh_class, escalation_policy, conflict_policy)
values
  ('is_renovated', 'Renovated unit', 'fittings', 'rent', 'floor_plan', '{"type": "string", "enum": ["confirmed", "advertised_unconfirmed", "none"]}'::jsonb, '{"type": "boolean"}'::jsonb, '[{"match": {"op": "eq", "value": "confirmed"}, "delta": 0.25}, {"match": {"op": "eq", "value": "advertised_unconfirmed"}, "delta": 0.0}, {"match": {"op": "eq", "value": "none"}, "delta": 0.0}]'::jsonb, 'True only when the Source explicitly states this unit or Floor Plan was renovated, remodeled, or updated (not merely modern finishes, new paint, or building-wide lobby work). Silence is unknown.', null, 'listing_details', 'available_sources_only', 'verified_positive_preferred'),
  ('year_built', 'Year built', 'amenities', 'rent', 'property', '{"type": "integer", "minimum": 1800, "maximum": 2030}'::jsonb, null, '[{"match": {"op": "gte", "value": 2010}, "delta": 0.5}, {"match": {"op": "range", "value": [2000, 2009]}, "delta": 0.25}, {"match": {"op": "range", "value": [1990, 1999]}, "delta": 0.0}, {"match": {"op": "lt", "value": 1990}, "delta": -0.25}]'::jsonb, 'Original construction or build year of the Property as a four-digit year. Use explicit page prose or embedded data only; ignore renovation or remodel dates unless they restate the original build year. Silence is unknown.', null, 'listing_details', 'available_sources_only', 'verified_positive_preferred')
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

