-- P3-7a2/P3-7b: classified images, Source-local Floor Plan associations, and
-- structured visual provenance. Extractions remain append-only.

alter table property_images
    add column source_id uuid references property_sources (id) on delete set null,
    add column source_page_order integer,
    add column is_current boolean not null default true,
    add column perceptual_hash text,
    add column normalization_profile text not null default 'webp-1024-q82-v1',
    add column discovery_context jsonb not null default '{}';

update property_images set kind = 'listing_photo' where kind is null;
alter table property_images
    alter column kind set default 'listing_photo',
    alter column kind set not null,
    add constraint property_images_kind_check
        check (kind in ('listing_photo', 'floor_plan_diagram', 'other')),
    add constraint property_images_perceptual_hash_check
        check (perceptual_hash is null or perceptual_hash ~ '^[0-9a-f]{16}$');

create index property_images_source_order_idx
    on property_images (source_id, is_current, source_page_order, created_at, id);

create table floor_plan_images (
    id uuid primary key default gen_random_uuid(),
    floor_plan_id uuid not null references floor_plans (id) on delete cascade,
    property_image_id uuid not null references property_images (id) on delete cascade,
    source_id uuid not null references property_sources (id) on delete cascade,
    action text not null check (action in ('link', 'unlink')),
    association_method text not null check (
        association_method in ('source_native_id', 'containing_card', 'nearby_label', 'manual')
    ),
    confidence confidence not null,
    evidence_context jsonb not null default '{}',
    display_order integer,
    actor_user_id uuid references auth.users (id) on delete set null,
    producer_job_id uuid references jobs (id) on delete set null,
    observed_at timestamptz not null default clock_timestamp()
);
create index floor_plan_images_current_idx
    on floor_plan_images (floor_plan_id, property_image_id, observed_at desc, id desc);

create view current_floor_plan_images
with (security_invoker = true)
as
select *
from (
    select fpi.*,
           row_number() over (
               partition by floor_plan_id, property_image_id
               order by observed_at desc, id desc
           ) as version_rank
    from floor_plan_images fpi
) ranked
where version_rank = 1 and action = 'link';

create table extraction_images (
    extraction_id uuid not null references extractions (id) on delete cascade,
    property_image_id uuid not null references property_images (id) on delete restrict,
    contribution_order integer not null default 0,
    primary key (extraction_id, property_image_id)
);
create index extraction_images_image_idx on extraction_images (property_image_id);

create function validate_visual_property_scope()
returns trigger language plpgsql as $$
declare
    left_property uuid;
    right_property uuid;
    source_property uuid;
begin
    if tg_table_name = 'floor_plan_images' then
        select property_id into left_property from floor_plans where id = new.floor_plan_id;
        select property_id into right_property from property_images where id = new.property_image_id;
        select property_id into source_property from property_sources where id = new.source_id;
    else
        select property_id into left_property from extractions where id = new.extraction_id;
        select property_id into right_property from property_images where id = new.property_image_id;
        source_property := left_property;
    end if;
    if left_property is null or left_property is distinct from right_property
       or left_property is distinct from source_property then
        raise exception 'visual provenance must remain within one Property';
    end if;
    return new;
end;
$$;

create trigger floor_plan_images_property_scope
before insert or update on floor_plan_images
for each row execute function validate_visual_property_scope();

create trigger extraction_images_property_scope
before insert or update on extraction_images
for each row execute function validate_visual_property_scope();

alter table floor_plan_images enable row level security;
alter table extraction_images enable row level security;

create policy floor_plan_images_authenticated_select
    on floor_plan_images for select to authenticated using (true);
create policy extraction_images_authenticated_select
    on extraction_images for select to authenticated using (true);

grant select on floor_plan_images, current_floor_plan_images, extraction_images to authenticated;
