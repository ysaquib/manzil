-- VC-7 — Fee Proposals: a tour offers a figure, it never writes one
-- (DESIGN §9.7, §8.2, §3 "Fee Proposal").
--
-- A tour produces the best cost data in the system — numbers a human confirmed
-- aloud with the agent standing there. They still do not write themselves. The
-- proposal is the offer; accepting performs the *ordinary* human write so every
-- provenance marker downstream keeps working unchanged, and rejecting records
-- the decision while leaving the Visit's own record alone: what the agent said
-- is still what the agent said.
create table visit_fee_proposals (
    id              uuid primary key default gen_random_uuid(),
    visit_id        uuid not null references visits (id) on delete cascade,
    -- Which door this figure came from. Null means it is about the property.
    visit_unit_id   uuid references visit_units (id) on delete set null,
    -- The Listing the offer is made to. A Visit hangs off a Property, which may
    -- carry more than one Listing, so the destination is named explicitly.
    hunt_listing_id uuid not null references hunt_listings (id) on delete cascade,
    -- The two destinations are genuinely different tables, so the proposal says
    -- which: recurring/move-in charges upsert `fee_checklist` in place, while
    -- base rent and all-in append to `overrides`. One shape, two accept paths.
    target          text not null check (target in ('fee_slot', 'override')),
    -- A `fee_slot` name, or an Override `criterion_key`.
    target_key      text not null check (char_length(target_key) between 1 and 120),
    amount          numeric(10, 2) not null check (amount >= 0),
    note            text check (char_length(note) <= 4000),
    status          text not null default 'pending'
                    check (status in ('pending', 'accepted', 'rejected')),
    decided_by      uuid references auth.users (id),
    decided_at      timestamptz,
    created_by      uuid not null references auth.users (id),
    created_at      timestamptz not null default now(),
    -- A decision is a pair: who and when travel together or the row is lying
    -- about having been decided.
    constraint visit_fee_proposals_decision_complete check (
        (status = 'pending' and decided_by is null and decided_at is null)
        or (status <> 'pending' and decided_by is not null and decided_at is not null)
    )
);

comment on table visit_fee_proposals is
    'A figure confirmed on a Visit, offered to a Listing for acceptance (DESIGN §9.7). '
    'Accepting performs the ordinary human write (fee_checklist upsert or overrides '
    'insert); rejecting writes only the decision and leaves the Visit untouched.';

comment on column visit_fee_proposals.target is
    'fee_slot -> upsert fee_checklist in place; override -> append to overrides.';

-- The drawer reads pending offers for one Listing; the checklist reads its own.
create index visit_fee_proposals_listing_idx
    on visit_fee_proposals (hunt_listing_id, status);
create index visit_fee_proposals_visit_idx on visit_fee_proposals (visit_id, created_at desc);

-- One live offer per destination: re-confirming a figure should update the
-- standing offer rather than stack a second one under the first, which would
-- make the drawer ask the same question twice with different numbers.
create unique index visit_fee_proposals_one_pending
    on visit_fee_proposals (visit_id, hunt_listing_id, target, target_key)
    where status = 'pending';

-- ---------------------------------------------------------------------------
-- Shape enforcement
--
-- Two cross-scope facts RLS cannot express: a proposal's unit must belong to
-- its own Visit, and the Listing it addresses must be the same Hunt *and* the
-- same Property the Visit was made at. Offering one building's confirmed rent
-- to another building's Listing is the failure worth being loud about.
-- ---------------------------------------------------------------------------

create function private.enforce_visit_fee_proposal_shape()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_hunt_id uuid;
    v_property_id uuid;
    l_hunt_id uuid;
    l_property_id uuid;
begin
    if new.visit_unit_id is not null and not exists (
        select 1 from public.visit_units u
        where u.id = new.visit_unit_id and u.visit_id = new.visit_id
    ) then
        raise exception 'visit unit % does not belong to visit %', new.visit_unit_id, new.visit_id
            using errcode = '23514';
    end if;

    select v.hunt_id, v.property_id into v_hunt_id, v_property_id
    from public.visits v where v.id = new.visit_id;

    select hl.hunt_id, hl.property_id into l_hunt_id, l_property_id
    from public.hunt_listings hl where hl.id = new.hunt_listing_id;

    if l_hunt_id is distinct from v_hunt_id then
        raise exception 'listing % is not in the visit''s hunt', new.hunt_listing_id
            using errcode = '23514';
    end if;

    if l_property_id is distinct from v_property_id then
        raise exception 'listing % is not the property that was visited', new.hunt_listing_id
            using errcode = '23514';
    end if;

    return new;
end;
$$;

create trigger visit_fee_proposals_enforce_shape
    before insert or update on visit_fee_proposals
    for each row execute function private.enforce_visit_fee_proposal_shape();

-- ---------------------------------------------------------------------------
-- RLS
--
-- Any member may *offer* a figure — whoever walked the unit heard it. Deciding
-- is the cost write, so it reuses the Override permission (§4.2): Owner and
-- Curator on any Listing, a Member only on Listings they added. That rule lives
-- in `private.can_write_listing_cost` so the API and the table cannot drift.
-- ---------------------------------------------------------------------------

create function private.can_write_listing_cost(p_hunt_listing_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.hunt_listings hl
        where hl.id = p_hunt_listing_id
          and (
              private.member_role(hl.hunt_id) in ('owner', 'curator')
              or (private.member_role(hl.hunt_id) = 'member' and hl.added_by = auth.uid())
          )
    );
$$;

revoke all on function private.can_write_listing_cost(uuid) from public, anon;
grant execute on function private.can_write_listing_cost(uuid) to authenticated;

comment on function private.can_write_listing_cost(uuid) is
    'Override/fee write permission (DESIGN §4.2): Owner and Curator on any '
    'Listing, Member only on their own. Accepting a Fee Proposal is a cost '
    'write, so it reuses this rather than inventing a second rule.';

alter table visit_fee_proposals enable row level security;

create policy visit_fee_proposals_member_read
    on visit_fee_proposals for select to authenticated
    using (private.member_role(private.visit_hunt_id(visit_id)) is not null);

create policy visit_fee_proposals_member_insert
    on visit_fee_proposals for insert to authenticated
    with check (
        created_by = auth.uid()
        and status = 'pending'
        and private.member_role(private.visit_hunt_id(visit_id)) is not null
    );

-- Deciding, or correcting a figure that has not been decided yet.
create policy visit_fee_proposals_decider_update
    on visit_fee_proposals for update to authenticated
    using (
        private.member_role(private.visit_hunt_id(visit_id)) is not null
        and (
            private.can_write_listing_cost(hunt_listing_id)
            or (status = 'pending' and created_by = auth.uid())
        )
    )
    with check (private.member_role(private.visit_hunt_id(visit_id)) is not null);

-- Withdrawing an offer nobody has acted on: the author's to take back.
create policy visit_fee_proposals_author_delete
    on visit_fee_proposals for delete to authenticated
    using (status = 'pending' and created_by = auth.uid());

alter publication supabase_realtime add table visit_fee_proposals;
