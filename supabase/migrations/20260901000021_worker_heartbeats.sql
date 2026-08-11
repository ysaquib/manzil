-- Dedicated worker liveness. Job locks remain the lease/recovery boundary;
-- this table answers whether a worker process is alive even while idle.
create table public.worker_heartbeats (
    worker_id text primary key,
    mode text not null check (mode in ('workflow', 'agents')),
    started_at timestamptz not null,
    last_seen_at timestamptz not null
);

create index worker_heartbeats_last_seen_idx
    on public.worker_heartbeats (last_seen_at desc);

alter table public.worker_heartbeats enable row level security;

revoke all on table public.worker_heartbeats from anon, authenticated;

comment on table public.worker_heartbeats is
    'Private worker-process liveness; stale rows are retained so Admin can distinguish unavailable workers.';
