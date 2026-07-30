-- Typed scoped claims may coexist by value while retaining independent scope.

alter table extractions
    add column claim_variant text,
    add constraint extractions_claim_variant_nonempty
        check (claim_variant is null or length(btrim(claim_variant)) > 0);

update extractions
set claim_variant = value #>> '{}'
where criterion_key in ('in_unit_laundry', 'parking', 'cooling', 'heating_type')
  and jsonb_typeof(value) = 'string';

update extractions
set claim_variant = (
    select jsonb_agg(item order by item)::text
    from jsonb_array_elements_text(value) as values_(item)
)
where criterion_key = 'flooring_materials'
  and jsonb_typeof(value) = 'array';

drop view current_extractions;
drop view current_extraction_candidates;

drop index extractions_current_candidate_global_idx;
drop index extractions_current_candidate_hunt_idx;
drop index extractions_current_resolved_global_idx;
drop index extractions_current_resolved_hunt_idx;

create index extractions_current_candidate_global_idx
    on extractions (
        property_id, criterion_key, origin_key, target_scope, floor_plan_id,
        claim_variant, extracted_at desc, id desc
    ) where record_kind = 'candidate' and hunt_id is null;
create index extractions_current_candidate_hunt_idx
    on extractions (
        property_id, hunt_id, criterion_key, origin_key, target_scope, floor_plan_id,
        claim_variant, extracted_at desc, id desc
    ) where record_kind = 'candidate' and hunt_id is not null;
create index extractions_current_resolved_global_idx
    on extractions (
        property_id, criterion_key, target_scope, floor_plan_id, claim_variant,
        extracted_at desc, id desc
    ) where record_kind = 'resolved' and hunt_id is null;
create index extractions_current_resolved_hunt_idx
    on extractions (
        property_id, hunt_id, criterion_key, target_scope, floor_plan_id,
        claim_variant, extracted_at desc, id desc
    ) where record_kind = 'resolved' and hunt_id is not null;

create view current_extraction_candidates
with (security_invoker = true)
as
select distinct on (
    property_id, hunt_id, criterion_key, origin_key, target_scope, floor_plan_id,
    claim_variant
)
    *
from extractions
where record_kind = 'candidate'
order by
    property_id, hunt_id, criterion_key, origin_key, target_scope, floor_plan_id,
    claim_variant, extracted_at desc, id desc;

create view current_extractions
with (security_invoker = true)
as
select distinct on (
    property_id, hunt_id, criterion_key, target_scope, floor_plan_id, claim_variant
)
    *
from extractions
where record_kind = 'resolved'
order by
    property_id, hunt_id, criterion_key, target_scope, floor_plan_id, claim_variant,
    extracted_at desc, id desc;

grant select on current_extraction_candidates, current_extractions to authenticated;

create or replace function private.validate_extraction_resolution_candidate()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
    resolution_row extractions%rowtype;
    candidate_row extractions%rowtype;
begin
    select * into resolution_row from extractions where id = new.resolution_extraction_id;
    select * into candidate_row from extractions where id = new.candidate_extraction_id;
    if resolution_row.record_kind <> 'resolved' or candidate_row.record_kind <> 'candidate' then
        raise exception 'resolution provenance must link resolved -> candidate rows';
    end if;
    if resolution_row.property_id <> candidate_row.property_id
       or resolution_row.hunt_id is distinct from candidate_row.hunt_id
       or resolution_row.criterion_key <> candidate_row.criterion_key
       or resolution_row.target_scope <> candidate_row.target_scope
       or resolution_row.floor_plan_id is distinct from candidate_row.floor_plan_id then
        raise exception 'resolution and candidate scoped identities differ';
    end if;
    return new;
end
$$;

update criteria_catalog
set value_schema = case key
        when 'in_unit_laundry' then
            '{"type":"array","items":{"type":"string","enum":["in_unit","hookups","on_site","none","advertised_unconfirmed"]},"minItems":1,"uniqueItems":true}'::jsonb
        when 'parking' then
            '{"type":"array","items":{"type":"string","enum":["garage","carport","covered","dedicated_lot","street_only","none","advertised_unconfirmed"]},"minItems":1,"uniqueItems":true}'::jsonb
        when 'cooling' then
            '{"type":"array","items":{"type":"string","enum":["central","window_units","none","advertised_unconfirmed"]},"minItems":1,"uniqueItems":true}'::jsonb
    end,
    default_options = (
        select jsonb_agg(
            jsonb_set(
                option,
                '{match}',
                jsonb_build_object(
                    'op', 'contains_any',
                    'value', jsonb_build_array(option #> '{match,value}')
                )
            )
            order by ordinal
        )
        from jsonb_array_elements(criteria_catalog.default_options)
             with ordinality as options(option, ordinal)
    )
where key in ('in_unit_laundry', 'parking', 'cooling');

with affected as (
    select distinct hunt_id
    from rubric_criteria
    where catalog_key in ('in_unit_laundry', 'parking', 'cooling')
),
rewritten as (
    update rubric_criteria criterion
    set options = (
        select jsonb_agg(
            case option #>> '{match,op}'
                when 'eq' then jsonb_set(
                    option,
                    '{match}',
                    jsonb_build_object(
                        'op', 'contains_any',
                        'value', jsonb_build_array(option #> '{match,value}')
                    )
                )
                when 'in' then jsonb_set(
                    option,
                    '{match,op}',
                    '"contains_any"'::jsonb
                )
                else option
            end
            order by ordinal
        )
        from jsonb_array_elements(criterion.options)
             with ordinality as options(option, ordinal)
    )
    where criterion.catalog_key in ('in_unit_laundry', 'parking', 'cooling')
    returning criterion.hunt_id
)
update hunts hunt
set rubric_version = rubric_version + 1
where hunt.id in (select hunt_id from affected);

insert into jobs (hunt_id, type, state, payload)
select affected.hunt_id, 'rescore', 'queued',
       jsonb_build_object('hunt_id', affected.hunt_id)
from (
    select distinct hunt_id
    from rubric_criteria
    where catalog_key in ('in_unit_laundry', 'parking', 'cooling')
) affected
where not exists (
    select 1
    from jobs
    where jobs.hunt_id = affected.hunt_id
      and jobs.type = 'rescore'
      and jobs.state in ('queued', 'running')
);
