-- VC-3 — the Visit Checklist answer store (DESIGN v3.30 §8.2, §9.7).
--
-- Append-only: the current value is the newest row per identity, resolved
-- through `current_visit_entries` and never by an ad-hoc "latest item" query.
-- That single shape buys three things at once — the byline history the UI shows,
-- the offline-conflict fork VC-6 detects through `prev_entry_id`, and
-- consistency with `extractions`/`overrides`/`floor_plan_images`.

-- ---------------------------------------------------------------------------
-- visit_entries
-- ---------------------------------------------------------------------------

create table visit_entries (
    id              uuid primary key default gen_random_uuid(),
    visit_id        uuid not null references visits (id) on delete cascade,
    -- A template item's `key`, or a `visit_custom_items.id` when is_custom.
    item_key        text not null check (char_length(item_key) between 1 and 120),
    is_custom       boolean not null default false,
    -- Null exactly when the item is property-scoped; the trigger below enforces
    -- that against the item's declared scope rather than trusting the caller.
    visit_unit_id   uuid references visit_units (id) on delete cascade,
    -- Null for shared items (Fact/Check/Question); set for an Impression, which
    -- is keyed per member. Part of the current-value identity.
    owner_user_id   uuid references auth.users (id),
    -- Always who wrote this row. This is the byline, and it is why shared items
    -- still attribute without a second table.
    author_user_id  uuid not null references auth.users (id),
    -- Null value is the revert tombstone, same idea as an Override's null row:
    -- clearing an answer appends rather than deletes, so history survives.
    value           jsonb,
    -- A Question's typed answer. Its presence *is* the checkmark (DESIGN §9.7),
    -- so it is deliberately not folded into `value`.
    answer_text     text check (char_length(answer_text) <= 4000),
    note            text check (char_length(note) <= 4000),
    -- The row its author believed was current. VC-6 compares this against the
    -- identity's actual current row to surface an offline fork; storing it now
    -- keeps that slice from needing a second migration.
    prev_entry_id   uuid references visit_entries (id) on delete set null,
    created_at      timestamptz not null default now()
);

comment on table visit_entries is
    'Append-only Visit Checklist answers (DESIGN §9.7). Current value = newest '
    '(created_at, id) per (visit_id, item_key, visit_unit_id, owner_user_id); '
    'read it through current_visit_entries, never directly.';

-- The current-value lookup, and the per-visit read the checklist page makes.
create index visit_entries_current_idx
    on visit_entries (visit_id, item_key, visit_unit_id, owner_user_id, created_at desc, id desc);
create index visit_entries_visit_idx on visit_entries (visit_id, created_at desc);
create index visit_entries_unit_idx on visit_entries (visit_unit_id) where visit_unit_id is not null;

-- ---------------------------------------------------------------------------
-- Shape enforcement
--
-- Scope is the *item's*, not the caller's. A property-scoped answer written
-- against a unit is not a preference to coerce — it is the mis-filed answer the
-- whole scope design exists to prevent, so it fails loudly. A trigger rather
-- than a check constraint because the rule needs the item's declared scope,
-- which lives in another table; a trigger also fires for a direct PostgREST
-- write, so the API is a mirror rather than the only guard.
-- ---------------------------------------------------------------------------

create function private.visit_item_shape(
    p_visit_id uuid,
    p_item_key text,
    p_is_custom boolean
)
returns table (kind text, scope text)
language sql
stable
security definer
set search_path = ''
as $$
    select ci.kind, ci.scope
    from public.visit_custom_items ci
    where p_is_custom
      and ci.visit_id = p_visit_id
      and ci.id::text = p_item_key
    union all
    select ti.kind, ti.scope
    from public.visit_template_items ti
    join public.visits v on v.id = p_visit_id
    where not p_is_custom
      and ti.key = p_item_key
      and ti.version = v.template_version
$$;

revoke all on function private.visit_item_shape(uuid, text, boolean) from public, anon;
grant execute on function private.visit_item_shape(uuid, text, boolean) to authenticated;

create function private.enforce_visit_entry_shape()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_kind text;
    v_scope text;
begin
    select shape.kind, shape.scope
      into v_kind, v_scope
      from private.visit_item_shape(new.visit_id, new.item_key, new.is_custom) as shape;

    if v_kind is null then
        raise exception 'unknown checklist item %', new.item_key
            using errcode = '23514';
    end if;

    if v_scope = 'unit' and new.visit_unit_id is null then
        raise exception 'checklist item % is unit-scoped and requires a visit_unit_id', new.item_key
            using errcode = '23514';
    end if;

    if v_scope = 'property' and new.visit_unit_id is not null then
        raise exception 'checklist item % is property-scoped and must not carry a visit_unit_id',
            new.item_key
            using errcode = '23514';
    end if;

    if new.visit_unit_id is not null and not exists (
        select 1 from public.visit_units u
        where u.id = new.visit_unit_id and u.visit_id = new.visit_id
    ) then
        raise exception 'visit unit % does not belong to visit %', new.visit_unit_id, new.visit_id
            using errcode = '23514';
    end if;

    -- An Impression belongs to exactly one member; a shared answer belongs to
    -- the visit. Getting this wrong would silently merge or split people's
    -- opinions, so it is checked rather than assumed.
    if v_kind = 'impression' then
        if new.owner_user_id is distinct from new.author_user_id then
            raise exception 'impression % must be owned by its author', new.item_key
                using errcode = '23514';
        end if;
    elsif new.owner_user_id is not null then
        raise exception 'shared checklist item % carries no owner_user_id', new.item_key
            using errcode = '23514';
    end if;

    return new;
end;
$$;

create trigger visit_entries_enforce_shape
    before insert on visit_entries
    for each row execute function private.enforce_visit_entry_shape();

-- ---------------------------------------------------------------------------
-- current_visit_entries — the one place the newest-per-identity rule lives
-- ---------------------------------------------------------------------------

create view current_visit_entries with (security_invoker = true) as
select distinct on (visit_id, item_key, visit_unit_id, owner_user_id)
    id,
    visit_id,
    item_key,
    is_custom,
    visit_unit_id,
    owner_user_id,
    author_user_id,
    value,
    answer_text,
    note,
    prev_entry_id,
    created_at
from visit_entries
order by visit_id, item_key, visit_unit_id, owner_user_id, created_at desc, id desc;

comment on view current_visit_entries is
    'Newest visit_entries row per (visit, item, unit, owner). security_invoker so '
    'it preserves the base table RLS rather than bypassing it (DESIGN §8.3).';

-- ---------------------------------------------------------------------------
-- RLS — read by the Hunt's members, appended by any member as themselves.
-- There is deliberately no UPDATE or DELETE policy: the table is append-only,
-- and clearing an answer means appending a null-valued tombstone.
-- ---------------------------------------------------------------------------

alter table visit_entries enable row level security;

create policy visit_entries_member_read
    on visit_entries for select to authenticated
    using (private.member_role(private.visit_hunt_id(visit_id)) is not null);

create policy visit_entries_member_insert
    on visit_entries for insert to authenticated
    with check (
        author_user_id = auth.uid()
        and private.member_role(private.visit_hunt_id(visit_id)) is not null
    );

alter publication supabase_realtime add table visit_entries;
