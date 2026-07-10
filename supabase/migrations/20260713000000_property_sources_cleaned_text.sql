-- Migration 0007: property_sources.cleaned_text (Phase-1 debugging artifact).
-- Debugging extraction confidence requires seeing the exact text the model saw;
-- today only cleaned_text_hash is stored, which proves identity but is useless
-- for auditing *why* a value was extracted. Plain nullable column, no default.
-- Deliberately NOT the §8.2 gzipped-Storage artifact: cleaned text is KB-scale
-- after cleaning, so an inline column is the pragmatic Phase-1 choice.
alter table property_sources add column if not exists cleaned_text text;
comment on column property_sources.cleaned_text is
  'Phase-1 debugging artifact: exact cleaned page text the extraction model saw '
  '(plain column instead of the §8.2 gzipped-Storage artifact; KB-scale after cleaning).';
