-- VC-1 — Visit Checklist foundations (DESIGN v3.30 §8.2, §8.3, §9.7).
--
-- A Visit is a tour of a Property by Hunt members, spanning every unit walked
-- on that occasion. It is Hunt opinion throughout: nothing here is an
-- Extraction, nothing reaches the scoring engine, and no row asserts that a
-- unit *exists* — only that somebody walked through a door and called it
-- something. §18's individual-unit-inventory deferral is untouched.
--
-- Entries, defects and fee proposals arrive in VC-3/VC-4/VC-7; this migration is
-- the identity and template substrate they hang off.

-- ---------------------------------------------------------------------------
-- Helpers that do not depend on the new tables
--
-- A SQL-language function body is parsed at creation, so the two helpers that
-- read `visits` are defined after the tables below rather than here.
-- ---------------------------------------------------------------------------

-- A Visit may only be created against a Property this Hunt actually holds; the
-- same cross-scope guard the cross-Property Floor Plan override already uses.
create function private.hunt_has_property(p_hunt_id uuid, p_property_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1 from public.hunt_listings hl
        where hl.hunt_id = p_hunt_id and hl.property_id = p_property_id
    )
$$;

revoke all on function private.hunt_has_property(uuid, uuid) from public, anon;
grant execute on function private.hunt_has_property(uuid, uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- visits
-- ---------------------------------------------------------------------------

create table visits (
    id               uuid primary key default gen_random_uuid(),
    hunt_id          uuid not null references hunts (id) on delete cascade,
    property_id      uuid not null references properties (id) on delete cascade,
    created_by       uuid not null references auth.users (id),
    scheduled_for    timestamptz,
    started_at       timestamptz,
    ended_at         timestamptz,
    cancelled_at     timestamptz,
    cancel_reason    text check (char_length(cancel_reason) <= 500),
    -- Frozen at creation: editing the template must never rewrite what a
    -- finished Visit asked, or what its completion percentage meant.
    template_version integer not null,
    -- A second showing may be seeded from the first so only changes get
    -- re-entered. ON DELETE SET NULL: losing the ancestor must not lose this.
    prefilled_from   uuid references visits (id) on delete set null,
    created_at       timestamptz not null default now(),

    -- State is *derived* from these timestamps (DESIGN §9.7), so the schema is
    -- shaped to make an incoherent state unrepresentable rather than merely
    -- discouraged: you cannot finish a tour that never started, cannot finish
    -- before starting, and cannot carry a cancellation reason without a
    -- cancellation.
    constraint visits_ended_requires_start check (ended_at is null or started_at is not null),
    constraint visits_ends_after_start check (
        started_at is null or ended_at is null or ended_at >= started_at
    ),
    constraint visits_reason_requires_cancel check (cancel_reason is null or cancelled_at is not null),
    constraint visits_no_self_prefill check (prefilled_from is null or prefilled_from <> id)
);

comment on table visits is
    'One tour of a Property by Hunt members (DESIGN §9.7). State is derived from '
    'started_at/ended_at/cancelled_at and never stored. Hunt opinion, not a fact.';

create index visits_hunt_created_idx on visits (hunt_id, created_at desc);
create index visits_property_idx on visits (property_id);
-- Serves "visits for this listing" in the drawer, the hottest read.
create index visits_hunt_property_idx on visits (hunt_id, property_id);

-- ---------------------------------------------------------------------------
-- visit_units
-- ---------------------------------------------------------------------------

create table visit_units (
    id            uuid primary key default gen_random_uuid(),
    visit_id      uuid not null references visits (id) on delete cascade,
    -- Always human-typed. There is no advertised unit list to select from: a
    -- Floor Plan is a marketed layout and a Unit Group is derived and unstored.
    label         text not null check (
        char_length(btrim(label)) between 1 and 80 and label = btrim(label)
    ),
    -- Null = a unit the listing never advertised. Normal, not an error.
    floor_plan_id uuid references floor_plans (id) on delete set null,
    beds          smallint not null check (beds between 0 and 20),
    baths         numeric(3, 1) not null check (
        baths >= 0 and baths <= 20 and (baths * 2) = trunc(baths * 2)
    ),
    -- Generated, not stored by the caller, and via the *existing* helper so the
    -- key is byte-identical to the one ratings/comments/pins already use —
    -- `2.0` baths must render "2", never "2.0", or the roll-up joins nothing.
    unit_group_key text generated always as (private.unit_group_key(beds, baths)) stored,
    display_order integer not null default 0,
    created_by    uuid not null references auth.users (id),
    created_at    timestamptz not null default now()
);

comment on table visit_units is
    'A door walked through on a Visit: a human-typed label plus either a Floor '
    'Plan pointer or typed (beds, baths). A label on a tour, never inventory — '
    'DESIGN §18''s individual-unit deferral is unaffected.';

create index visit_units_visit_idx on visit_units (visit_id, display_order, created_at);
create index visit_units_group_idx on visit_units (unit_group_key);
create index visit_units_floor_plan_idx on visit_units (floor_plan_id) where floor_plan_id is not null;

-- ---------------------------------------------------------------------------
-- visit_template_items — global seeded reference data, like criteria_catalog
-- ---------------------------------------------------------------------------

create table visit_template_items (
    key           text not null,
    version       integer not null,
    section_key   text not null,
    -- Globally monotonic, so section grouping *and* section order both derive
    -- from the items. There is deliberately no sections table (DESIGN §8.2);
    -- human-readable section titles are frontend copy.
    display_order integer not null,
    tier          text not null check (tier in ('quick', 'standard', 'thorough')),
    kind          text not null check (kind in ('fact', 'check', 'question', 'impression')),
    scope         text not null check (scope in ('property', 'unit')),
    label         text not null check (char_length(label) between 1 and 300),
    help          text check (char_length(help) <= 500),
    -- A check's tri-state is implied by its kind, so it carries no schema.
    value_schema  jsonb not null default '{}'::jsonb,
    is_critical   boolean not null default false,
    primary key (version, key),
    constraint visit_template_check_has_no_schema check (
        kind <> 'check' or value_schema = '{}'::jsonb
    ),
    constraint visit_template_noncheck_has_schema check (
        kind = 'check' or value_schema <> '{}'::jsonb
    )
);

comment on table visit_template_items is
    'The built-in Visit Checklist template. Generated from '
    'api/src/manzil_api/visits/template.py; a parity test asserts this migration '
    'still matches that module. Service-role writes only.';

create index visit_template_items_order_idx on visit_template_items (version, display_order);

-- ---------------------------------------------------------------------------
-- visit_custom_items — per-Visit additions, always rendered as custom
-- ---------------------------------------------------------------------------

create table visit_custom_items (
    id          uuid primary key default gen_random_uuid(),
    visit_id    uuid not null references visits (id) on delete cascade,
    section_key text not null check (char_length(section_key) between 1 and 60),
    kind        text not null check (kind in ('fact', 'check', 'question', 'impression')),
    scope       text not null check (scope in ('property', 'unit')),
    label       text not null check (
        char_length(btrim(label)) between 1 and 300 and label = btrim(label)
    ),
    created_by  uuid not null references auth.users (id),
    created_at  timestamptz not null default now()
);

comment on table visit_custom_items is
    'Per-Visit checklist additions (DESIGN §9.7). Hunt-wide recurring items and '
    'Rubric-derived items are deferred (§18).';

create index visit_custom_items_visit_idx on visit_custom_items (visit_id, created_at);

-- ---------------------------------------------------------------------------
-- Helpers that read the new tables
-- ---------------------------------------------------------------------------

-- Child policies need a Visit's Hunt without themselves reading `visits`
-- through RLS, which would recurse. SECURITY DEFINER, like `member_role`.
create function private.visit_hunt_id(p_visit_id uuid)
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
    select hunt_id from public.visits where id = p_visit_id
$$;

-- A Visit Unit may point at a Floor Plan only of its own Visit's Property.
-- Null is always allowed: a described unit the listing never advertised is the
-- normal case, not an error.
create function private.visit_allows_floor_plan(p_visit_id uuid, p_floor_plan_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select p_floor_plan_id is null or exists (
        select 1
        from public.visits v
        join public.floor_plans fp on fp.id = p_floor_plan_id
        where v.id = p_visit_id and fp.property_id = v.property_id
    )
$$;

revoke all on function private.visit_hunt_id(uuid) from public, anon;
revoke all on function private.visit_allows_floor_plan(uuid, uuid) from public, anon;
grant execute on function private.visit_hunt_id(uuid) to authenticated;
grant execute on function private.visit_allows_floor_plan(uuid, uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- Update rules that a column-level RLS predicate cannot express
-- ---------------------------------------------------------------------------

-- RLS `with check` sees only NEW, so "any member may start or end a Visit, but
-- only its creator or the Owner may cancel one" is not expressible as a policy —
-- it is a statement about which column changed. A trigger fires for a direct
-- PostgREST write too, so this remains a real boundary rather than an API
-- convention.
create function private.enforce_visit_update_rules()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.hunt_id is distinct from old.hunt_id
        or new.property_id is distinct from old.property_id
        or new.created_by is distinct from old.created_by
        or new.template_version is distinct from old.template_version then
        raise exception 'visit identity columns are immutable'
            using errcode = '42501';
    end if;

    -- No authenticated subject means a service-role/worker context, which
    -- bypasses RLS by design; the permission rule below concerns members.
    if auth.uid() is null then
        return new;
    end if;

    if new.cancelled_at is distinct from old.cancelled_at
        and old.created_by <> auth.uid()
        and coalesce(private.member_role(old.hunt_id)::text, '') <> 'owner' then
        raise exception 'only the visit creator or the hunt owner may cancel or reinstate a visit'
            using errcode = '42501';
    end if;

    return new;
end;
$$;

create trigger visits_enforce_update_rules
    before update on visits
    for each row execute function private.enforce_visit_update_rules();

-- ---------------------------------------------------------------------------
-- RLS (DESIGN §4.2, §8.3)
-- ---------------------------------------------------------------------------

alter table visits enable row level security;
alter table visit_units enable row level security;
alter table visit_template_items enable row level security;
alter table visit_custom_items enable row level security;

-- Every member of the owning Hunt reads; any member creates.
create policy visits_member_read
    on visits for select to authenticated
    using (private.member_role(hunt_id) is not null);

create policy visits_member_insert
    on visits for insert to authenticated
    with check (
        created_by = auth.uid()
        and private.member_role(hunt_id) is not null
        and private.hunt_has_property(hunt_id, property_id)
    );

-- Any member may start, end or reschedule. The cancel narrowing and the
-- immutable-column rule live in the trigger above.
create policy visits_member_update
    on visits for update to authenticated
    using (private.member_role(hunt_id) is not null)
    with check (
        private.member_role(hunt_id) is not null
        and private.hunt_has_property(hunt_id, property_id)
    );

-- Delete narrows to the creator or the Owner. This one *is* expressible as a
-- policy, because DELETE only needs the old row.
create policy visits_creator_or_owner_delete
    on visits for delete to authenticated
    using (created_by = auth.uid() or private.member_role(hunt_id) = 'owner');

create policy visit_units_member_read
    on visit_units for select to authenticated
    using (private.member_role(private.visit_hunt_id(visit_id)) is not null);

create policy visit_units_member_insert
    on visit_units for insert to authenticated
    with check (
        created_by = auth.uid()
        and private.member_role(private.visit_hunt_id(visit_id)) is not null
        and private.visit_allows_floor_plan(visit_id, floor_plan_id)
    );

create policy visit_units_member_update
    on visit_units for update to authenticated
    using (private.member_role(private.visit_hunt_id(visit_id)) is not null)
    with check (
        private.member_role(private.visit_hunt_id(visit_id)) is not null
        and private.visit_allows_floor_plan(visit_id, floor_plan_id)
    );

create policy visit_units_member_delete
    on visit_units for delete to authenticated
    using (private.member_role(private.visit_hunt_id(visit_id)) is not null);

-- Global read-only reference data. No write policy exists at all: the template
-- changes by migration, never by a client.
create policy visit_template_items_read
    on visit_template_items for select to authenticated
    using (true);

create policy visit_custom_items_member_read
    on visit_custom_items for select to authenticated
    using (private.member_role(private.visit_hunt_id(visit_id)) is not null);

create policy visit_custom_items_member_insert
    on visit_custom_items for insert to authenticated
    with check (
        created_by = auth.uid()
        and private.member_role(private.visit_hunt_id(visit_id)) is not null
    );

create policy visit_custom_items_creator_or_owner_delete
    on visit_custom_items for delete to authenticated
    using (
        created_by = auth.uid()
        or private.member_role(private.visit_hunt_id(visit_id)) = 'owner'
    );

-- ---------------------------------------------------------------------------
-- Realtime (DESIGN §13.3). Entries/defects/proposals join in their own slices.
-- ---------------------------------------------------------------------------

alter publication supabase_realtime add table visits;
alter publication supabase_realtime add table visit_units;
alter publication supabase_realtime add table visit_custom_items;

-- ---------------------------------------------------------------------------
-- Template seed — generated by api/src/manzil_api/visits/template.py.
-- Do not hand-edit: `test_visit_template.py` asserts this block still matches
-- the module, and a new template version gets a new migration.
-- ---------------------------------------------------------------------------

insert into visit_template_items (
    key, version, section_key, display_order, tier, kind, scope,
    label, help, value_schema, is_critical
) values
    ('ess_budget', 1, 'essentials', 1, 'quick', 'check', 'unit', 'Total monthly cost is within budget', null, '{}'::jsonb, false),
    ('ess_bedrooms', 1, 'essentials', 2, 'quick', 'check', 'unit', 'Bedroom count and size work', null, '{}'::jsonb, false),
    ('ess_laundry', 1, 'essentials', 3, 'quick', 'check', 'unit', 'In-unit laundry, or an acceptable alternative', null, '{}'::jsonb, false),
    ('ess_pets', 1, 'essentials', 4, 'quick', 'check', 'property', 'Pet policy works', null, '{}'::jsonb, false),
    ('ess_parking', 1, 'essentials', 5, 'quick', 'check', 'property', 'Parking works', null, '{}'::jsonb, false),
    ('ess_safe', 1, 'essentials', 6, 'quick', 'check', 'property', 'Feels safe', null, '{}'::jsonb, false),
    ('ess_commute', 1, 'essentials', 7, 'quick', 'check', 'property', 'Commute is acceptable', null, '{}'::jsonb, false),
    ('ess_available', 1, 'essentials', 8, 'quick', 'check', 'unit', 'Available when you need it', null, '{}'::jsonb, false),
    ('sweep_pressure', 1, 'sweep', 9, 'quick', 'check', 'unit', 'Run the kitchen tap and the shower at the same time', 'Does the pressure hold?', '{}'::jsonb, false),
    ('sweep_hot_water_secs', 1, 'sweep', 10, 'quick', 'fact', 'unit', 'Hot water arrives in', null, '{"type": "integer", "unit": "sec"}'::jsonb, false),
    ('sweep_hot_water_stays', 1, 'sweep', 11, 'quick', 'check', 'unit', 'Hot water stays hot', null, '{}'::jsonb, false),
    ('sweep_toilets', 1, 'sweep', 12, 'quick', 'check', 'unit', 'Flush every toilet', null, '{}'::jsonb, false),
    ('sweep_heat_ac', 1, 'sweep', 13, 'quick', 'check', 'unit', 'Turn on the heat, then the A/C', 'Do both respond?', '{}'::jsonb, false),
    ('sweep_under_sinks', 1, 'sweep', 14, 'quick', 'check', 'unit', 'Look under every sink', 'Leaks, stains, warped wood', '{}'::jsonb, false),
    ('sweep_windows', 1, 'sweep', 15, 'standard', 'check', 'unit', 'Open, close and lock every window', null, '{}'::jsonb, false),
    ('sweep_outlets', 1, 'sweep', 16, 'standard', 'check', 'unit', 'Test an outlet in each room', 'A phone charger is enough', '{}'::jsonb, false),
    ('sweep_smells', 1, 'sweep', 17, 'quick', 'fact', 'unit', 'Smell test', null, '{"options": ["mildew", "smoke", "pets", "sewage", "air_freshener_masking", "nothing_unusual"], "type": "multiselect"}'::jsonb, false),
    ('sweep_heard', 1, 'sweep', 18, 'quick', 'fact', 'unit', 'Stand still and listen for 60 seconds', null, '{"options": ["traffic", "neighbours", "hallway", "hvac", "plumbing", "trains_or_planes", "bar_or_restaurant", "construction", "nothing"], "type": "multiselect"}'::jsonb, false),
    ('sweep_cell_bars', 1, 'sweep', 19, 'quick', 'fact', 'unit', 'Cell signal in the worst room', null, '{"type": "integer", "unit": "bars"}'::jsonb, false),
    ('sweep_actual_unit', 1, 'sweep', 20, 'quick', 'fact', 'unit', 'Is this the actual unit you''d rent, or a model?', null, '{"options": ["actual", "model"], "type": "enum"}'::jsonb, true),
    ('prep_reviews', 1, 'prep', 21, 'standard', 'check', 'property', 'Read the online reviews', null, '{}'::jsonb, false),
    ('prep_review_pattern', 1, 'prep', 22, 'standard', 'fact', 'property', 'Pattern of complaints', null, '{"type": "text"}'::jsonb, false),
    ('prep_crime', 1, 'prep', 23, 'standard', 'check', 'property', 'Checked area crime and safety data', null, '{}'::jsonb, false),
    ('prep_flood', 1, 'prep', 24, 'standard', 'check', 'property', 'Checked flood risk', null, '{}'::jsonb, false),
    ('prep_commute_min', 1, 'prep', 25, 'quick', 'fact', 'property', 'Commute at your real departure hour', null, '{"type": "integer", "unit": "min"}'::jsonb, false),
    ('prep_errands', 1, 'prep', 26, 'standard', 'check', 'property', 'Looked up grocery, pharmacy, gym and place-of-worship distances', null, '{}'::jsonb, false),
    ('prep_internet', 1, 'prep', 27, 'standard', 'check', 'property', 'Checked which internet providers serve the address, and max speed', null, '{}'::jsonb, false),
    ('prep_building_age', 1, 'prep', 28, 'standard', 'fact', 'property', 'Building age', 'Pre-1978 means a lead-paint disclosure is required by law', '{"type": "integer"}'::jsonb, false),
    ('prep_construction', 1, 'prep', 29, 'thorough', 'check', 'property', 'Searched for planned construction or demolition nearby', null, '{}'::jsonb, false),
    ('prep_nonnegotiables', 1, 'prep', 30, 'thorough', 'check', 'property', 'Wrote down your non-negotiables', null, '{}'::jsonb, false),
    ('prep_still_available', 1, 'prep', 31, 'quick', 'check', 'property', 'Confirmed the units are still available', null, '{}'::jsonb, false),
    ('kitchen_fridge', 1, 'kitchen', 32, 'standard', 'impression', 'unit', 'Fridge', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('kitchen_stove', 1, 'kitchen', 33, 'standard', 'impression', 'unit', 'Stove', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('kitchen_oven', 1, 'kitchen', 34, 'standard', 'impression', 'unit', 'Oven', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('kitchen_dishwasher', 1, 'kitchen', 35, 'standard', 'impression', 'unit', 'Dishwasher', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('kitchen_microwave', 1, 'kitchen', 36, 'thorough', 'impression', 'unit', 'Microwave', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('kitchen_stove_type', 1, 'kitchen', 37, 'standard', 'fact', 'unit', 'Stove type', null, '{"options": ["gas", "electric", "induction"], "type": "enum"}'::jsonb, false),
    ('kitchen_opened', 1, 'kitchen', 38, 'standard', 'check', 'unit', 'Opened the fridge, oven and dishwasher', null, '{}'::jsonb, false),
    ('kitchen_disposal', 1, 'kitchen', 39, 'standard', 'check', 'unit', 'Ran the disposal', null, '{}'::jsonb, false),
    ('kitchen_hood_vents_outside', 1, 'kitchen', 40, 'standard', 'check', 'unit', 'Exhaust hood vents outside', 'Not recirculating — matters a lot for heavy cooking', '{}'::jsonb, false),
    ('kitchen_counter_space', 1, 'kitchen', 41, 'thorough', 'check', 'unit', 'Counter space works for how you actually cook', null, '{}'::jsonb, false),
    ('kitchen_cabinets_open', 1, 'kitchen', 42, 'thorough', 'check', 'unit', 'Cabinets and drawers open fully, no collisions', null, '{}'::jsonb, false),
    ('kitchen_cabinet_interiors', 1, 'kitchen', 43, 'standard', 'check', 'unit', 'Looked inside the cabinets', 'Droppings, water stains, smell', '{}'::jsonb, false),
    ('kitchen_counter_outlets', 1, 'kitchen', 44, 'thorough', 'fact', 'unit', 'Counter outlets', null, '{"type": "integer"}'::jsonb, false),
    ('kitchen_storage', 1, 'kitchen', 45, 'standard', 'fact', 'unit', 'Storage', null, '{"options": ["generous", "adequate", "tight"], "type": "enum"}'::jsonb, false),
    ('kitchen_notes', 1, 'kitchen', 46, 'standard', 'impression', 'unit', 'Notes', null, '{"type": "text"}'::jsonb, false),
    ('bath_count', 1, 'bathrooms', 47, 'quick', 'fact', 'unit', 'Bathrooms', null, '{"type": "integer"}'::jsonb, false),
    ('bath_pressure', 1, 'bathrooms', 48, 'quick', 'check', 'unit', 'Shower pressure is strong', null, '{}'::jsonb, false),
    ('bath_drains', 1, 'bathrooms', 49, 'standard', 'check', 'unit', 'Drains fast', 'Run it a full minute', '{}'::jsonb, false),
    ('bath_toilet', 1, 'bathrooms', 50, 'standard', 'check', 'unit', 'Toilet flushes and refills normally', null, '{}'::jsonb, false),
    ('bath_fan', 1, 'bathrooms', 51, 'standard', 'check', 'unit', 'Exhaust fan works and is vented', 'Run it — is it deafening?', '{}'::jsonb, false),
    ('bath_mildew', 1, 'bathrooms', 52, 'quick', 'check', 'unit', 'No mildew in grout, caulk or ceiling corners', null, '{}'::jsonb, false),
    ('bath_soft_spots', 1, 'bathrooms', 53, 'standard', 'check', 'unit', 'No soft spots or discolouration around the toilet or tub base', null, '{}'::jsonb, false),
    ('bath_storage', 1, 'bathrooms', 54, 'thorough', 'check', 'unit', 'Storage is adequate', null, '{}'::jsonb, false),
    ('bath_door_locks', 1, 'bathrooms', 55, 'thorough', 'check', 'unit', 'Door closes and locks', null, '{}'::jsonb, false),
    ('bath_type', 1, 'bathrooms', 56, 'standard', 'fact', 'unit', 'Bathing', null, '{"options": ["tub", "standing_shower", "both"], "type": "enum"}'::jsonb, false),
    ('bath_condition', 1, 'bathrooms', 57, 'standard', 'impression', 'unit', 'Condition', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('bathrooms_notes', 1, 'bathrooms', 58, 'standard', 'impression', 'unit', 'Notes', null, '{"type": "text"}'::jsonb, false),
    ('bed_count', 1, 'bedrooms', 59, 'quick', 'fact', 'unit', 'Bedrooms', null, '{"type": "integer"}'::jsonb, false),
    ('bed_window_each', 1, 'bedrooms', 60, 'quick', 'check', 'unit', 'Every bedroom has a window', 'Fire-code requirement', '{}'::jsonb, false),
    ('bed_fits', 1, 'bedrooms', 61, 'standard', 'check', 'unit', 'Your bed fits with walking room', 'Measure it', '{}'::jsonb, false),
    ('bed_closet_width', 1, 'bedrooms', 62, 'standard', 'fact', 'unit', 'Closet width', null, '{"type": "number", "unit": "in"}'::jsonb, false),
    ('bed_closet_type', 1, 'bedrooms', 63, 'standard', 'fact', 'unit', 'Closet type', null, '{"options": ["reach_in", "walk_in", "wardrobe_only", "none"], "type": "enum"}'::jsonb, false),
    ('bed_doors_latch', 1, 'bedrooms', 64, 'thorough', 'check', 'unit', 'Doors close and latch properly', null, '{}'::jsonb, false),
    ('bed_outlets', 1, 'bedrooms', 65, 'thorough', 'check', 'unit', 'Outlets usefully placed relative to the bed', null, '{}'::jsonb, false),
    ('bed_overhead_light', 1, 'bedrooms', 66, 'standard', 'check', 'unit', 'Overhead light or ceiling fan present', null, '{}'::jsonb, false),
    ('bed_window_direction', 1, 'bedrooms', 67, 'thorough', 'fact', 'unit', 'Window direction', null, '{"options": ["n", "ne", "e", "se", "s", "sw", "w", "nw"], "type": "enum"}'::jsonb, false),
    ('bed_light_quality', 1, 'bedrooms', 68, 'standard', 'impression', 'unit', 'Light quality', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('bedrooms_notes', 1, 'bedrooms', 69, 'standard', 'impression', 'unit', 'Notes', null, '{"type": "text"}'::jsonb, false),
    ('living_light_level', 1, 'living', 70, 'quick', 'fact', 'unit', 'Natural light', null, '{"options": ["bright", "moderate", "dark"], "type": "enum"}'::jsonb, false),
    ('living_windows_operate', 1, 'living', 71, 'standard', 'check', 'unit', 'Windows open, close and lock', null, '{}'::jsonb, false),
    ('living_screens', 1, 'living', 72, 'thorough', 'check', 'unit', 'Screens present and intact', null, '{}'::jsonb, false),
    ('living_insulated', 1, 'living', 73, 'standard', 'check', 'unit', 'Double-pane, or feels insulated', null, '{}'::jsonb, false),
    ('living_drafts', 1, 'living', 74, 'standard', 'check', 'unit', 'No drafts at the frames or doors', null, '{}'::jsonb, false),
    ('living_blinds', 1, 'living', 75, 'thorough', 'check', 'unit', 'Blinds or curtains included and in good condition', null, '{}'::jsonb, false),
    ('living_walls', 1, 'living', 76, 'standard', 'check', 'unit', 'Walls and ceilings free of cracks, stains and patch marks', null, '{}'::jsonb, false),
    ('living_floors_level', 1, 'living', 77, 'standard', 'check', 'unit', 'Floors are level', 'No bounce, slope or squeak', '{}'::jsonb, false),
    ('living_flooring_type', 1, 'living', 78, 'standard', 'fact', 'unit', 'Flooring', null, '{"options": ["carpet", "hardwood", "engineered_wood", "laminate", "vinyl", "tile", "concrete", "other"], "type": "enum"}'::jsonb, false),
    ('living_flooring_condition', 1, 'living', 79, 'standard', 'impression', 'unit', 'Flooring condition', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('living_view', 1, 'living', 80, 'standard', 'fact', 'unit', 'The actual view', null, '{"type": "text"}'::jsonb, false),
    ('living_balcony', 1, 'living', 81, 'standard', 'fact', 'unit', 'Balcony or patio', null, '{"options": ["yes", "no"], "type": "enum"}'::jsonb, false),
    ('living_balcony_detail', 1, 'living', 82, 'thorough', 'fact', 'unit', 'Balcony size and condition', null, '{"type": "text"}'::jsonb, false),
    ('living_notes', 1, 'living', 83, 'standard', 'impression', 'unit', 'Notes', null, '{"type": "text"}'::jsonb, false),
    ('laundry_type', 1, 'laundry', 84, 'quick', 'fact', 'unit', 'Laundry', null, '{"options": ["in_unit", "shared_in_building", "off_site", "hookups_only"], "type": "enum"}'::jsonb, false),
    ('laundry_config', 1, 'laundry', 85, 'thorough', 'fact', 'unit', 'Configuration', null, '{"options": ["full_size", "stacked", "combo"], "type": "enum"}'::jsonb, false),
    ('laundry_venting', 1, 'laundry', 86, 'thorough', 'fact', 'unit', 'Venting', null, '{"options": ["vented", "ventless"], "type": "enum"}'::jsonb, false),
    ('laundry_powered_on', 1, 'laundry', 87, 'standard', 'check', 'unit', 'Powered them on', null, '{}'::jsonb, false),
    ('laundry_shared_machines', 1, 'laundry', 88, 'thorough', 'fact', 'property', 'Shared machines', null, '{"type": "integer"}'::jsonb, false),
    ('laundry_shared_cost', 1, 'laundry', 89, 'thorough', 'fact', 'property', 'Cost per load', null, '{"type": "money"}'::jsonb, false),
    ('laundry_shared_payment', 1, 'laundry', 90, 'thorough', 'fact', 'property', 'Payment', null, '{"options": ["card", "coin", "app"], "type": "enum"}'::jsonb, false),
    ('laundry_shared_hours', 1, 'laundry', 91, 'thorough', 'fact', 'property', 'Hours', null, '{"type": "text"}'::jsonb, false),
    ('laundry_notes', 1, 'laundry', 92, 'standard', 'impression', 'unit', 'Notes', null, '{"type": "text"}'::jsonb, false),
    ('sys_heat_type', 1, 'systems', 93, 'standard', 'fact', 'unit', 'Heating', null, '{"options": ["forced_air", "radiator", "baseboard", "heat_pump", "other"], "type": "enum"}'::jsonb, false),
    ('sys_cooling_type', 1, 'systems', 94, 'standard', 'fact', 'unit', 'Cooling', null, '{"options": ["central", "window", "mini_split", "none"], "type": "enum"}'::jsonb, false),
    ('sys_thermostat', 1, 'systems', 95, 'standard', 'check', 'unit', 'Thermostat is in-unit and you control it', null, '{}'::jsonb, false),
    ('sys_vents', 1, 'systems', 96, 'standard', 'check', 'unit', 'Vents in every room, unobstructed', null, '{}'::jsonb, false),
    ('sys_insulation', 1, 'systems', 97, 'thorough', 'check', 'unit', 'Insulation feels adequate', 'Cold walls? Drafty corners?', '{}'::jsonb, false),
    ('sys_rust_water', 1, 'systems', 98, 'standard', 'check', 'unit', 'No rust-coloured water after 30 seconds', null, '{}'::jsonb, false),
    ('sys_water_heater', 1, 'systems', 99, 'standard', 'fact', 'unit', 'Water heater', null, '{"options": ["in_unit", "shared"], "type": "enum"}'::jsonb, false),
    ('sys_water_heater_size', 1, 'systems', 100, 'thorough', 'fact', 'unit', 'Water heater size or capacity', null, '{"type": "text"}'::jsonb, false),
    ('sys_sump_pump', 1, 'systems', 101, 'thorough', 'check', 'unit', 'Sump pump present and appears functional, if applicable', null, '{}'::jsonb, false),
    ('sys_gfci', 1, 'systems', 102, 'standard', 'check', 'unit', 'GFCI outlets in the kitchen and bathrooms', null, '{}'::jsonb, false),
    ('sys_panel', 1, 'systems', 103, 'standard', 'fact', 'unit', 'Panel', 'Fuses mean old wiring', '{"options": ["breakers", "fuses"], "type": "enum"}'::jsonb, false),
    ('sys_switches', 1, 'systems', 104, 'thorough', 'check', 'unit', 'All switches work, no flicker', null, '{}'::jsonb, false),
    ('sys_desk_outlets', 1, 'systems', 105, 'thorough', 'check', 'unit', 'Enough outlets for a desk or office setup', null, '{}'::jsonb, false),
    ('systems_notes', 1, 'systems', 106, 'standard', 'impression', 'unit', 'Notes', null, '{"type": "text"}'::jsonb, false),
    ('noise_walls', 1, 'noise', 107, 'standard', 'fact', 'unit', 'Knocked on the shared walls', null, '{"options": ["solid", "hollow"], "type": "enum"}'::jsonb, false),
    ('noise_floor', 1, 'noise', 108, 'standard', 'fact', 'unit', 'Floor', null, '{"options": ["top", "middle", "ground"], "type": "enum"}'::jsonb, false),
    ('noise_neighbours', 1, 'noise', 109, 'standard', 'fact', 'unit', 'Neighbours', null, '{"options": ["above", "below", "side"], "type": "multiselect"}'::jsonb, false),
    ('noise_adjacent', 1, 'noise', 110, 'standard', 'fact', 'unit', 'Adjacent to', null, '{"options": ["elevator", "stairwell", "trash_chute", "laundry", "parking", "mechanical"], "type": "multiselect"}'::jsonb, false),
    ('noise_front_door', 1, 'noise', 111, 'thorough', 'check', 'unit', 'Front door doesn''t open onto a high-traffic area', null, '{}'::jsonb, false),
    ('noise_window_facing', 1, 'noise', 112, 'thorough', 'check', 'unit', 'Windows don''t face another unit''s windows', null, '{}'::jsonb, false),
    ('noise_quietness', 1, 'noise', 113, 'quick', 'impression', 'unit', 'Quietness', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('noise_notes', 1, 'noise', 114, 'standard', 'impression', 'unit', 'Notes', null, '{"type": "text"}'::jsonb, false),
    ('space_living_dims', 1, 'space', 115, 'standard', 'fact', 'unit', 'Living room size, ft by ft', null, '{"type": "text"}'::jsonb, false),
    ('space_bed1_dims', 1, 'space', 116, 'standard', 'fact', 'unit', 'Bedroom 1 size, ft by ft', null, '{"type": "text"}'::jsonb, false),
    ('space_bed2_dims', 1, 'space', 117, 'thorough', 'fact', 'unit', 'Bedroom 2 size, ft by ft', null, '{"type": "text"}'::jsonb, false),
    ('space_front_door_width', 1, 'space', 118, 'thorough', 'fact', 'unit', 'Front door width', null, '{"type": "number", "unit": "in"}'::jsonb, false),
    ('space_couch_fits', 1, 'space', 119, 'standard', 'check', 'unit', 'The stairwell or elevator can handle a couch', null, '{}'::jsonb, false),
    ('space_coat_closet', 1, 'space', 120, 'thorough', 'check', 'unit', 'Coat or linen closet', null, '{}'::jsonb, false),
    ('space_layout', 1, 'space', 121, 'standard', 'impression', 'unit', 'Layout works for how you live', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('space_awkward', 1, 'space', 122, 'thorough', 'fact', 'unit', 'Awkward or wasted space', null, '{"type": "text"}'::jsonb, false),
    ('space_notes', 1, 'space', 123, 'standard', 'impression', 'unit', 'Notes', null, '{"type": "text"}'::jsonb, false),
    ('safety_smoke_detectors', 1, 'safety', 124, 'quick', 'fact', 'unit', 'Smoke detectors', null, '{"type": "integer"}'::jsonb, false),
    ('safety_co_detector', 1, 'safety', 125, 'quick', 'check', 'unit', 'CO detector', null, '{}'::jsonb, false),
    ('safety_sprinklers', 1, 'safety', 126, 'thorough', 'check', 'unit', 'Sprinklers or an extinguisher', null, '{}'::jsonb, false),
    ('safety_deadbolt', 1, 'safety', 127, 'quick', 'check', 'unit', 'Deadbolt on the entry door', null, '{}'::jsonb, false),
    ('safety_peephole', 1, 'safety', 128, 'thorough', 'check', 'unit', 'Peephole or camera', null, '{}'::jsonb, false),
    ('safety_ground_windows', 1, 'safety', 129, 'thorough', 'check', 'unit', 'Ground-floor windows lock securely', null, '{}'::jsonb, false),
    ('safety_two_exits', 1, 'safety', 130, 'standard', 'check', 'unit', 'Two exit routes from the unit and the building', null, '{}'::jsonb, false),
    ('safety_secure_entry', 1, 'safety', 131, 'quick', 'check', 'property', 'Secure building entry — fob, code or buzzer', null, '{}'::jsonb, false),
    ('safety_lot_lighting', 1, 'safety', 132, 'standard', 'check', 'property', 'Exterior and lot are well lit', 'If you toured by day, drive by at night', '{}'::jsonb, false),
    ('safety_packages', 1, 'safety', 133, 'standard', 'fact', 'property', 'How package delivery is secured', null, '{"type": "text"}'::jsonb, false),
    ('safety_cameras', 1, 'safety', 134, 'thorough', 'check', 'property', 'Cameras in the common areas', null, '{}'::jsonb, false),
    ('safety_felt', 1, 'safety', 135, 'quick', 'impression', 'property', 'Felt safety', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('safety_notes', 1, 'safety', 136, 'standard', 'impression', 'property', 'Notes', null, '{"type": "text"}'::jsonb, false),
    ('bldg_common_areas', 1, 'building', 137, 'standard', 'impression', 'property', 'Hallways, stairwells and laundry', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('bldg_trash_area', 1, 'building', 138, 'standard', 'impression', 'property', 'Trash and recycling area', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('bldg_mailboxes', 1, 'building', 139, 'standard', 'check', 'property', 'Mailboxes are secure', null, '{}'::jsonb, false),
    ('bldg_elevator', 1, 'building', 140, 'thorough', 'check', 'property', 'Elevator working', null, '{}'::jsonb, false),
    ('bldg_grounds', 1, 'building', 141, 'standard', 'check', 'property', 'Grounds maintained, no obvious deferred maintenance', null, '{}'::jsonb, false),
    ('bldg_parking_type', 1, 'building', 142, 'quick', 'fact', 'property', 'Parking', null, '{"options": ["assigned", "first_come", "street", "garage"], "type": "enum"}'::jsonb, false),
    ('bldg_parking_cost', 1, 'building', 143, 'quick', 'fact', 'property', 'Parking cost', null, '{"type": "money"}'::jsonb, false),
    ('bldg_guest_parking', 1, 'building', 144, 'thorough', 'check', 'property', 'Guest parking', null, '{}'::jsonb, false),
    ('bldg_snow_removal', 1, 'building', 145, 'thorough', 'fact', 'property', 'Snow removal handled by', null, '{"type": "text"}'::jsonb, false),
    ('bldg_snow_piles', 1, 'building', 146, 'thorough', 'question', 'property', 'Where does the plowed snow get piled?', 'Does it block your spot?', '{"type": "text"}'::jsonb, false),
    ('bldg_bike_storage', 1, 'building', 147, 'thorough', 'check', 'property', 'Bike storage', null, '{}'::jsonb, false),
    ('bldg_extra_storage_cost', 1, 'building', 148, 'thorough', 'fact', 'property', 'Extra storage unit, per month', null, '{"type": "money"}'::jsonb, false),
    ('bldg_amenities', 1, 'building', 149, 'standard', 'fact', 'property', 'Amenities', null, '{"options": ["gym", "pool", "clubhouse", "rooftop", "coworking", "ev_charging", "other"], "type": "multiselect"}'::jsonb, false),
    ('bldg_saw_amenities', 1, 'building', 150, 'standard', 'check', 'property', 'Actually saw them', null, '{}'::jsonb, false),
    ('bldg_amenity_fee', 1, 'building', 151, 'standard', 'fact', 'property', 'Amenity fee, per month', null, '{"type": "money"}'::jsonb, false),
    ('bldg_amenity_fee_required', 1, 'building', 152, 'standard', 'fact', 'property', 'Amenity fee is', null, '{"options": ["optional", "mandatory"], "type": "enum"}'::jsonb, false),
    ('building_notes', 1, 'building', 153, 'standard', 'impression', 'property', 'Notes', null, '{"type": "text"}'::jsonb, false),
    ('pets_allowed', 1, 'pets', 154, 'quick', 'fact', 'property', 'Pets allowed', null, '{"options": ["yes", "no"], "type": "enum"}'::jsonb, false),
    ('pets_types', 1, 'pets', 155, 'standard', 'fact', 'property', 'Types and limits', null, '{"type": "text"}'::jsonb, false),
    ('pets_max', 1, 'pets', 156, 'standard', 'fact', 'property', 'Maximum number', null, '{"type": "integer"}'::jsonb, false),
    ('pets_restrictions', 1, 'pets', 157, 'standard', 'fact', 'property', 'Weight or breed restrictions', null, '{"type": "text"}'::jsonb, false),
    ('pets_onetime_fee', 1, 'pets', 158, 'standard', 'fact', 'property', 'One-time fee', null, '{"type": "money"}'::jsonb, false),
    ('pets_deposit', 1, 'pets', 159, 'standard', 'fact', 'property', 'Deposit', null, '{"type": "money"}'::jsonb, false),
    ('pets_deposit_refundable', 1, 'pets', 160, 'standard', 'fact', 'property', 'Pet deposit refundable', null, '{"options": ["yes", "no"], "type": "enum"}'::jsonb, false),
    ('pets_rent', 1, 'pets', 161, 'standard', 'fact', 'property', 'Pet rent, per month', null, '{"type": "money"}'::jsonb, false),
    ('pets_green_space', 1, 'pets', 162, 'thorough', 'check', 'property', 'Green space nearby', null, '{}'::jsonb, false),
    ('pets_other_pets', 1, 'pets', 163, 'thorough', 'check', 'property', 'Other tenants'' pets — any noise or smell?', null, '{}'::jsonb, false),
    ('pets_notes', 1, 'pets', 164, 'standard', 'impression', 'property', 'Notes', null, '{"type": "text"}'::jsonb, false),
    ('flag_agent_evasive', 1, 'red_flags', 165, 'quick', 'impression', 'property', 'Agent rushed, dodged, or wouldn''t show the actual unit', null, '{"type": "boolean"}'::jsonb, false),
    ('flag_pressure', 1, 'red_flags', 166, 'quick', 'impression', 'property', 'Pressure to apply on the spot or pay a hold fee today', null, '{"type": "boolean"}'::jsonb, false),
    ('flag_contradiction', 1, 'red_flags', 167, 'quick', 'impression', 'property', 'Something the agent said contradicted the listing', null, '{"type": "boolean"}'::jsonb, false),
    ('flag_common_areas_worse', 1, 'red_flags', 168, 'standard', 'impression', 'property', 'Common areas noticeably worse than the unit shown', null, '{"type": "boolean"}'::jsonb, false),
    ('flag_vacancies', 1, 'red_flags', 169, 'standard', 'impression', 'property', 'Many vacant units, or high turnover', null, '{"type": "boolean"}'::jsonb, false),
    ('flag_fresh_paint', 1, 'red_flags', 170, 'standard', 'impression', 'property', 'Fresh paint or caulk in one isolated spot', null, '{"type": "boolean"}'::jsonb, false),
    ('flag_pests', 1, 'red_flags', 171, 'quick', 'impression', 'property', 'Pest traps, glue boards or droppings visible', null, '{"type": "boolean"}'::jsonb, false),
    ('flag_latches', 1, 'red_flags', 172, 'standard', 'impression', 'property', 'Doors or windows that won''t latch', 'Possible settling', '{"type": "boolean"}'::jsonb, false),
    ('flag_details', 1, 'red_flags', 173, 'standard', 'impression', 'property', 'Details', null, '{"type": "text"}'::jsonb, false),
    ('money_total_monthly', 1, 'money', 174, 'quick', 'question', 'unit', 'What is the total monthly cost — rent plus every mandatory fee?', null, '{"type": "text"}'::jsonb, true),
    ('money_utilities_included', 1, 'money', 175, 'quick', 'question', 'unit', 'Which utilities are included?', null, '{"type": "text"}'::jsonb, true),
    ('money_utility_history', 1, 'money', 176, 'standard', 'question', 'unit', 'Can I see 12 months of actual utility bills for this unit?', 'For this unit — not a building average', '{"type": "text"}'::jsonb, false),
    ('money_fees_refundable', 1, 'money', 177, 'quick', 'question', 'property', 'Deposit, application fee, admin fee — and is the application fee refundable if I''m denied?', null, '{"type": "text"}'::jsonb, true),
    ('money_deposit_nonrefundable', 1, 'money', 178, 'standard', 'question', 'property', 'What makes the deposit non-refundable?', null, '{"type": "text"}'::jsonb, false),
    ('money_move_in_total', 1, 'money', 179, 'standard', 'fact', 'unit', 'Move-in total', null, '{"type": "money"}'::jsonb, false),
    ('money_concession_amortized', 1, 'money', 180, 'standard', 'question', 'property', 'Is any move-in special amortized across the lease?', 'That is what makes the renewal jump', '{"type": "text"}'::jsonb, false),
    ('money_payment_method', 1, 'money', 181, 'thorough', 'fact', 'property', 'Rent payment', null, '{"options": ["portal", "check", "ach"], "type": "enum"}'::jsonb, false),
    ('money_convenience_fee', 1, 'money', 182, 'thorough', 'fact', 'property', 'Convenience fee', null, '{"type": "money"}'::jsonb, false),
    ('money_late_fee', 1, 'money', 183, 'thorough', 'fact', 'property', 'Late fee', null, '{"type": "money"}'::jsonb, false),
    ('money_grace_days', 1, 'money', 184, 'thorough', 'fact', 'property', 'Grace period', null, '{"type": "integer", "unit": "days"}'::jsonb, false),
    ('money_notes', 1, 'money', 185, 'standard', 'impression', 'unit', 'Notes', null, '{"type": "text"}'::jsonb, false),
    ('lease_lengths', 1, 'lease', 186, 'quick', 'question', 'property', 'What lease lengths are available?', null, '{"type": "text"}'::jsonb, false),
    ('lease_mtm_premium', 1, 'lease', 187, 'thorough', 'fact', 'property', 'Month-to-month premium', null, '{"type": "money"}'::jsonb, false),
    ('lease_renewal_increase', 1, 'lease', 188, 'quick', 'question', 'property', 'How much did rent increase for renewing tenants this year?', null, '{"type": "text"}'::jsonb, true),
    ('lease_notice', 1, 'lease', 189, 'quick', 'question', 'property', 'How much notice must I give to not renew, and what happens if I miss it?', null, '{"type": "text"}'::jsonb, true),
    ('lease_early_termination', 1, 'lease', 190, 'standard', 'question', 'property', 'What is the early-termination penalty?', null, '{"type": "text"}'::jsonb, false),
    ('lease_auto_moveout_charges', 1, 'lease', 191, 'quick', 'question', 'property', 'What charges are automatic at move-out regardless of condition?', null, '{"type": "text"}'::jsonb, true),
    ('lease_deposit_return_days', 1, 'lease', 192, 'standard', 'fact', 'property', 'Deposit return timeline', null, '{"type": "integer", "unit": "days"}'::jsonb, false),
    ('lease_sublet', 1, 'lease', 193, 'thorough', 'question', 'property', 'What is the subletting policy?', null, '{"type": "text"}'::jsonb, false),
    ('lease_guests', 1, 'lease', 194, 'thorough', 'question', 'property', 'What is the long-term guest policy?', null, '{"type": "text"}'::jsonb, false),
    ('lease_entry_notice_hrs', 1, 'lease', 195, 'standard', 'fact', 'property', 'Landlord entry notice', null, '{"type": "integer", "unit": "hrs"}'::jsonb, false),
    ('lease_alterations', 1, 'lease', 196, 'standard', 'question', 'property', 'Rules on painting, mounting TVs and shelves?', null, '{"type": "text"}'::jsonb, false),
    ('lease_smoking', 1, 'lease', 197, 'quick', 'question', 'property', 'Is the building smoke-free, does that include marijuana, and how is it enforced?', null, '{"type": "text"}'::jsonb, true),
    ('lease_quiet_hours', 1, 'lease', 198, 'thorough', 'fact', 'property', 'Quiet hours', null, '{"type": "text"}'::jsonb, false),
    ('lease_insurance_min', 1, 'lease', 199, 'thorough', 'fact', 'property', 'Renters insurance minimum', null, '{"type": "text"}'::jsonb, false),
    ('lease_blank_copy', 1, 'lease', 200, 'standard', 'check', 'property', 'Requested a blank copy of the lease before applying', null, '{}'::jsonb, false),
    ('lease_move_in_inspection', 1, 'lease', 201, 'standard', 'check', 'property', 'Move-in inspection form provided', null, '{}'::jsonb, false),
    ('app_requirements', 1, 'application', 202, 'quick', 'question', 'property', 'What are the income and credit requirements?', null, '{"type": "text"}'::jsonb, true),
    ('app_fee', 1, 'application', 203, 'quick', 'fact', 'property', 'Application fee', null, '{"type": "money"}'::jsonb, false),
    ('app_fee_refundable', 1, 'application', 204, 'standard', 'fact', 'property', 'Refundable if denied', null, '{"options": ["yes", "no"], "type": "enum"}'::jsonb, false),
    ('app_guarantor', 1, 'application', 205, 'thorough', 'question', 'property', 'Is a guarantor or co-signer accepted, and on what terms?', null, '{"type": "text"}'::jsonb, false),
    ('app_count_in', 1, 'application', 206, 'thorough', 'question', 'property', 'How many applications are already in on this unit?', null, '{"type": "text"}'::jsonb, false),
    ('app_hold', 1, 'application', 207, 'thorough', 'question', 'property', 'Can the unit be held, and at what cost?', null, '{"type": "text"}'::jsonb, false),
    ('app_decision_days', 1, 'application', 208, 'standard', 'fact', 'property', 'Decision turnaround', null, '{"type": "integer", "unit": "days"}'::jsonb, false),
    ('app_disqualifiers', 1, 'application', 209, 'standard', 'question', 'property', 'What would disqualify an application?', null, '{"type": "text"}'::jsonb, false),
    ('hist_bed_bugs', 1, 'history', 210, 'quick', 'question', 'property', 'Has this unit or building had bed bugs in the last two years?', 'And what is the treatment protocol?', '{"type": "text"}'::jsonb, true),
    ('hist_maintenance', 1, 'history', 211, 'quick', 'question', 'property', 'How do maintenance requests work, what is the typical turnaround, and is there a 24/7 emergency line?', null, '{"type": "text"}'::jsonb, true),
    ('hist_vacancy', 1, 'history', 212, 'quick', 'question', 'unit', 'How long has this unit been vacant, and why did the last tenant leave?', null, '{"type": "text"}'::jsonb, true),
    ('hist_pest_schedule', 1, 'history', 213, 'standard', 'question', 'property', 'What is the pest-control schedule?', null, '{"type": "text"}'::jsonb, false),
    ('hist_leaks', 1, 'history', 214, 'standard', 'question', 'unit', 'Any leaks, burst pipes, backups or flooding in this unit?', null, '{"type": "text"}'::jsonb, false),
    ('hist_ice_dams', 1, 'history', 215, 'thorough', 'question', 'property', 'Any ice dams or roof leaks?', null, '{"type": "text"}'::jsonb, false),
    ('hist_hvac_age', 1, 'history', 216, 'thorough', 'fact', 'unit', 'Furnace/AC age and last filter change', null, '{"type": "text"}'::jsonb, false),
    ('hist_rekeyed', 1, 'history', 217, 'standard', 'question', 'property', 'Are the locks re-keyed between tenants?', null, '{"type": "text"}'::jsonb, false),
    ('hist_break_ins', 1, 'history', 218, 'standard', 'question', 'property', 'Any break-ins or package theft in the last year?', null, '{"type": "text"}'::jsonb, false),
    ('hist_noise_complaints', 1, 'history', 219, 'thorough', 'question', 'unit', 'Any noise complaints on file for this unit?', null, '{"type": "text"}'::jsonb, false),
    ('hist_management', 1, 'history', 220, 'standard', 'fact', 'property', 'Management', null, '{"options": ["on_site", "off_site"], "type": "enum"}'::jsonb, false),
    ('hist_renovations', 1, 'history', 221, 'thorough', 'question', 'property', 'What was renovated or replaced, and when?', null, '{"type": "text"}'::jsonb, false),
    ('hist_lead_paint', 1, 'history', 222, 'standard', 'check', 'property', 'Lead-paint disclosure provided', 'Required by law for pre-1978 buildings', '{}'::jsonb, false),
    ('hist_planned_work', 1, 'history', 223, 'standard', 'question', 'property', 'Any planned construction or renovation during my lease?', null, '{"type": "text"}'::jsonb, false),
    ('hist_closing_question', 1, 'history', 224, 'quick', 'question', 'property', 'Is there anything about this unit or building you''d want to know if you were me?', null, '{"type": "text"}'::jsonb, false),
    ('follow_night_drive', 1, 'followup', 225, 'standard', 'check', 'property', 'Drove by at night', null, '{}'::jsonb, false),
    ('follow_rush_hour', 1, 'followup', 226, 'standard', 'check', 'property', 'Checked the commute at rush hour', null, '{}'::jsonb, false),
    ('follow_street_parking', 1, 'followup', 227, 'thorough', 'check', 'property', 'Checked street parking in the evening', null, '{}'::jsonb, false),
    ('follow_read_lease', 1, 'followup', 228, 'standard', 'check', 'property', 'Read the actual lease', null, '{}'::jsonb, false),
    ('follow_tenant_said', 1, 'followup', 229, 'thorough', 'fact', 'property', 'What a current tenant said', null, '{"type": "text"}'::jsonb, false),
    ('follow_internet_verified', 1, 'followup', 230, 'standard', 'check', 'property', 'Verified internet speeds at this address', null, '{}'::jsonb, false),
    ('follow_claims_crosschecked', 1, 'followup', 231, 'standard', 'check', 'property', 'Cross-checked the agent''s claims against reviews', null, '{}'::jsonb, false),
    ('follow_repairs_in_writing', 1, 'followup', 232, 'standard', 'check', 'property', 'Confirmed repair promises in writing', null, '{}'::jsonb, false),
    ('follow_still_to_ask', 1, 'followup', 233, 'standard', 'fact', 'property', 'Still need to ask', null, '{"type": "text"}'::jsonb, false),
    ('verdict_price_value', 1, 'verdict_unit', 234, 'quick', 'impression', 'unit', 'Price and value', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('verdict_condition', 1, 'verdict_unit', 235, 'quick', 'impression', 'unit', 'Unit condition', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('verdict_size_layout', 1, 'verdict_unit', 236, 'quick', 'impression', 'unit', 'Size and layout', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('verdict_noise', 1, 'verdict_unit', 237, 'quick', 'impression', 'unit', 'Noise', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('verdict_light', 1, 'verdict_unit', 238, 'quick', 'impression', 'unit', 'Light', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('verdict_could_live', 1, 'verdict_unit', 239, 'quick', 'impression', 'unit', 'Could you live here for a year?', null, '{"options": ["yes", "maybe", "no"], "type": "enum"}'::jsonb, false),
    ('verdict_call', 1, 'verdict_unit', 240, 'quick', 'impression', 'unit', 'Verdict', null, '{"options": ["apply_now", "strong_contender", "backup", "pass"], "type": "enum"}'::jsonb, false),
    ('verdict_loved', 1, 'verdict_unit', 241, 'standard', 'impression', 'unit', 'What you loved', null, '{"type": "text"}'::jsonb, false),
    ('verdict_bothered', 1, 'verdict_unit', 242, 'standard', 'impression', 'unit', 'What bothered you', null, '{"type": "text"}'::jsonb, false),
    ('verdict_dealbreakers', 1, 'verdict_unit', 243, 'quick', 'impression', 'unit', 'Dealbreakers', null, '{"type": "text"}'::jsonb, false),
    ('verdict_safety', 1, 'verdict_property', 244, 'quick', 'impression', 'property', 'Felt safety', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('verdict_location_commute', 1, 'verdict_property', 245, 'quick', 'impression', 'property', 'Location and commute', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('verdict_management', 1, 'verdict_property', 246, 'quick', 'impression', 'property', 'Management impression', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('verdict_common_areas', 1, 'verdict_property', 247, 'standard', 'impression', 'property', 'Common areas', null, '{"max": 5, "type": "rating"}'::jsonb, false),
    ('verdict_property_notes', 1, 'verdict_property', 248, 'standard', 'impression', 'property', 'Notes on the building', null, '{"type": "text"}'::jsonb, false);
