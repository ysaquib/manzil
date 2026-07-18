-- catalog_sync: location_safety → A+..F letter grades (DESIGN §20 2026-07-18;
-- IMPLEMENTATION §8 "Catalog changes on hosted DB").
--
-- seed.sql is local-reset-only; this migration carries the same row change to
-- the hosted DB. Value literals mirror the generator's output exactly — if
-- shared/catalog.py and this row ever disagree, catalog.py is the source and a
-- new sync migration is owed.
--
-- Data impact: none. No pipeline stage has ever emitted location_safety (it is
-- excluded from the EXTRACT schema by requires_tool and P3-8 ships it as an
-- override-first placeholder), so no extraction rows exist to remap and no
-- rescore is needed — an unknown scores unknown_delta under either vocabulary.
-- Rubric rows that still carry old low/medium/high default options are
-- rewritten to the new banded defaults below; hand-tuned options (any row not
-- matching the old defaults verbatim) are left alone for their owner to revisit.

insert into criteria_catalog
  (key, label, category, domain, value_schema, default_options, extraction_hint, requires_tool, refresh_class)
values
  ('location_safety', 'Location safety', 'location', 'rent', '{"type": "string", "enum": ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F"]}'::jsonb, '[{"match": {"op": "eq", "value": "A+"}, "delta": 0.5}, {"match": {"op": "eq", "value": "A"}, "delta": 0.5}, {"match": {"op": "eq", "value": "A-"}, "delta": 0.5}, {"match": {"op": "eq", "value": "B+"}, "delta": 0.25}, {"match": {"op": "eq", "value": "B"}, "delta": 0.25}, {"match": {"op": "eq", "value": "B-"}, "delta": 0.25}, {"match": {"op": "eq", "value": "C+"}, "delta": 0.0}, {"match": {"op": "eq", "value": "C"}, "delta": 0.0}, {"match": {"op": "eq", "value": "C-"}, "delta": 0.0}, {"match": {"op": "eq", "value": "D+"}, "delta": -0.5}, {"match": {"op": "eq", "value": "D"}, "delta": -0.5}, {"match": {"op": "eq", "value": "D-"}, "delta": -0.5}, {"match": {"op": "eq", "value": "F"}, "delta": -1.0}]'::jsonb, 'Letter-grade location safety (A+ through F). Placeholder in v1: no pipeline stage emits it — the value arrives via human override until the dedicated safety module (DESIGN §18, P3-17) lands. Inherently low-confidence by design (DESIGN R8) — frame as such, never as fact.', 'web_search', 'reviews')
on conflict (key) do update set
  label = excluded.label,
  category = excluded.category,
  domain = excluded.domain,
  value_schema = excluded.value_schema,
  default_options = excluded.default_options,
  extraction_hint = excluded.extraction_hint,
  requires_tool = excluded.requires_tool,
  refresh_class = excluded.refresh_class;

-- Rewrite untouched old-default rubric options to the new defaults (exact match
-- on the pre-change default_options only — hand-tuned rubrics are not ours to
-- rewrite here).
update rubric_criteria
set options = (select default_options from criteria_catalog where key = 'location_safety')
where catalog_key = 'location_safety'
  and options = '[{"match": {"op": "eq", "value": "high"}, "delta": 0.5}, {"match": {"op": "eq", "value": "medium"}, "delta": 0.0}, {"match": {"op": "eq", "value": "low"}, "delta": -1.0}]'::jsonb;
