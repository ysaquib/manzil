-- Per-stage job cost (AD-C). `jobs.cost_actual_usd` answers "what did this Job
-- cost"; it cannot answer "which stage got expensive", which is the question an
-- operator actually has. One row per (job, stage), split by what bought it.
--
-- Deliberately per STAGE, not per call: per-call telemetry is Langfuse's job and
-- there is no reason to reinvent it here. Stage granularity keeps the table
-- roughly one order of magnitude smaller than the call log while still
-- localizing spend to something actionable.

create table job_stage_costs (
    job_id uuid not null references jobs (id) on delete cascade,
    stage  text not null,

    -- Token spend: what the model call billed, including the native-search
    -- charges the seam prices explicitly.
    llm_calls          integer not null default 0 check (llm_calls >= 0),
    -- 6 decimals, not 4. A single tier-3 request is $0.0015 and a cached-read
    -- token charge is smaller still; `numeric(12,4)` is one order of magnitude
    -- from truncating a real line item to zero. `jobs.cost_actual_usd` keeps its
    -- 4 decimals because it holds a sum, which is never that small.
    llm_cost_usd       numeric(12, 6) not null default 0 check (llm_cost_usd >= 0),
    input_tokens       bigint not null default 0 check (input_tokens >= 0),
    output_tokens      bigint not null default 0 check (output_tokens >= 0),
    cache_read_tokens  bigint not null default 0 check (cache_read_tokens >= 0),
    cache_write_tokens bigint not null default 0 check (cache_write_tokens >= 0),

    -- Non-LLM spend: managed-unblocker (tier 3) requests. Invisible before AD-C,
    -- because the tally was token-shaped and tier 3 has no tokens at all.
    fetch_calls    integer not null default 0 check (fetch_calls >= 0),
    fetch_cost_usd numeric(12, 6) not null default 0 check (fetch_cost_usd >= 0),
    -- provider name -> calls. Per provider because the price is per provider: a
    -- blended count could not be re-priced after a provider switch, and the free
    -- plan's monthly credit allowance is also counted per provider.
    fetch_calls_by_provider jsonb not null default '{}'::jsonb,

    updated_at timestamptz not null default now(),

    primary key (job_id, stage)
);

comment on table job_stage_costs is
    'Per-(job, stage) spend split into LLM and fetch channels (AD-C). Written by '
    'the worker at each persist-before-advance point; replaced, not accumulated, '
    'when a stage re-runs.';
comment on column job_stage_costs.fetch_cost_usd is
    'Managed-unblocker spend priced from TIER3_PRICES_USD. An unpriced provider '
    'records calls with cost 0 rather than a guess.';

-- The Costs view reads "spend by stage across a window" and "this Job''s split".
-- The PK covers the per-Job read; this covers the cross-Job aggregate.
create index job_stage_costs_stage_updated_idx on job_stage_costs (stage, updated_at desc);
-- Partial: the monthly credit counter only ever scans rows that used tier 3,
-- which is a small minority of stages.
create index job_stage_costs_fetch_idx on job_stage_costs (updated_at desc)
    where fetch_calls > 0;

alter table job_stage_costs enable row level security;

-- Mirrors job_events_member_select exactly: visible to members of the Hunt that
-- owns the Job, and to nobody else. No client write policy at all — the worker
-- writes through a direct pool connection, and a cost row a member could forge
-- is a cost row that means nothing.
create policy job_stage_costs_member_select
    on job_stage_costs for select to authenticated
    using (
        exists (
            select 1 from jobs j
            where j.id = job_stage_costs.job_id
              and private.member_role(j.hunt_id) is not null
        )
    );

-- Tier-3 credit usage per provider per month. The free plan is a fixed monthly
-- allowance (5,000 credits for Bright Data) that resets on the 1st, so the
-- interesting number is always "this calendar month" — exhausting it silently
-- drops tier 3 off the fetch ladder mid-run.
--
-- security_invoker so the view honors the base table's RLS instead of running as
-- its owner; without it this view would leak every Hunt's fetch volume.
create view tier3_credit_usage
with (security_invoker = on) as
select
    date_trunc('month', jsc.updated_at) as month,
    usage.key                           as provider,
    sum(usage.value::bigint)            as credits
from job_stage_costs jsc,
     lateral jsonb_each_text(jsc.fetch_calls_by_provider) as usage
group by 1, 2;

comment on view tier3_credit_usage is
    'Tier-3 requests per provider per calendar month — the counter behind the '
    'free plan''s monthly credit allowance.';
