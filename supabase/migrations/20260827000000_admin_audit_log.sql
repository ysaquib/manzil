-- Admin audit log (AD-1, DESIGN §20 v3.39).
--
-- The one place a general-purpose audit log genuinely earns its keep. Everywhere
-- else, Manzil records history in the domain table that owns the fact — which is
-- why AD-G added append-only companions instead of a global event stream. Admin
-- actions have no such table: nothing in the schema can record "an admin opened
-- a Hunt they are not a member of", because from the schema's point of view
-- nothing happened. They also reach across tenants and include irreversible
-- operations, which is exactly the shape that deserves its own ledger.
--
-- Written by the admin router before it returns, inside the request. An admin
-- action that is not attributable is worse than one that is not possible.

create table admin_audit_log (
    id uuid primary key default gen_random_uuid(),
    -- No FK to auth.users: deleting an admin's account must never erase what
    -- they did. Same reasoning as AD-G's tombstones.
    admin_user_id uuid not null,
    -- Dotted verb naming the operation, e.g. `user.suspend`, `hunt.view_as_owner`.
    action text not null check (char_length(action) between 1 and 100),
    -- What it acted on. Both nullable: `admin.grant` has no Hunt, and a bulk
    -- retry has no single target.
    target_type text check (char_length(target_type) <= 50),
    target_id   uuid,
    hunt_id     uuid,
    -- Human-readable at the time of the action, so a reader is not left holding
    -- an id whose row has since been deleted.
    target_label text,
    -- Before/after for a mutation. A diff, not a full row snapshot: the point is
    -- what the admin changed, and full snapshots would make this table the
    -- largest in the database while answering the same question.
    before jsonb,
    after  jsonb,
    -- Ghost-view context: which Hunt the admin was standing in, and whether they
    -- were a genuine member of it at the time. That distinction changes how the
    -- action should be read, and it cannot be reconstructed later — membership
    -- may have changed since.
    via_ghost_view boolean not null default false,
    request_id text,
    occurred_at timestamptz not null default now()
);

comment on table admin_audit_log is
    'Every Site Admin mutation (AD-1). Written by the admin router before it '
    'returns. No SELECT policy: read it with service_role, through the panel.';

create index admin_audit_log_recent_idx on admin_audit_log (occurred_at desc);
create index admin_audit_log_admin_idx on admin_audit_log (admin_user_id, occurred_at desc);
create index admin_audit_log_hunt_idx on admin_audit_log (hunt_id, occurred_at desc)
    where hunt_id is not null;

alter table admin_audit_log enable row level security;
-- No policies at all — the same posture as `feedback` and `site_admins`. An
-- audit log its subjects can edit is not an audit log, and one they can read
-- would let a compromised account enumerate operator activity. The panel reads
-- it through the service-role admin router.

-- Append-only even for `service_role`, which is what the admin router runs as
-- and therefore the only caller with the reach to rewrite history here. RLS
-- cannot express this: service_role bypasses it entirely.
create or replace function private.admin_audit_log_is_append_only()
returns trigger language plpgsql
as $$
begin
    raise exception 'admin_audit_log is append-only' using errcode = '42501';
end;
$$;

create trigger admin_audit_log_no_rewrite
before update or delete on admin_audit_log
for each row execute function private.admin_audit_log_is_append_only();
