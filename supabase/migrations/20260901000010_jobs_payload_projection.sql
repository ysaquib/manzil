-- Cleaned Source text is readable by every Hunt member through `jobs.payload`
-- (`.claude/plans/cleaned-text-exposure.md`, DESIGN §16 control 2, §17).
--
-- DM-1 revoked `property_sources.cleaned_text` and DESIGN then claimed cleaned
-- Source text was service-role-only "for every member, not only for demo". It
-- was not: `payload.run_state.sources[].cleaned_text` is the same page body, and
-- `jobs` is member-selectable. The front door was locked while a side door
-- stood open. 5330 characters of page text were readable through it with an
-- ordinary member's JWT on this database.
--
-- The fix is on the READ side. The text stays where the worker's resume path
-- expects it and becomes unreadable, rather than being stripped on write:
-- stripping means rewinding a resume that starts past FETCH, which fails
-- silently (an emptied Source is *skipped* at `extract.py:336`, not an error).
-- Present-but-unreadable is weaker than absent -- a future view, admin export or
-- support tool could still reach it -- and that residual is recorded in §17.
--
-- Four moving parts:
--   1. `private.strip_cleaned_text` -- a total jsonb transform.
--   2. `jobs.payload_public` -- a STORED generated column the database
--      maintains, so it is correct for every writer, not only the worker.
--   3. the column grants -- `payload` withheld from `authenticated`/`anon`.
--   4. the two `authenticated` RPCs that used to hand back a whole `jobs` row.
--
-- Operationally: adding a STORED generated column takes ACCESS EXCLUSIVE and
-- rewrites `jobs`, detoasting and re-TOASTing every payload. Seconds at this
-- scale; the worker blocks on it for that long.

-- ── 1. The transform ─────────────────────────────────────────────────────────
-- Two properties this function must have, and both are load-bearing:
--
-- **Total.** It must never raise, on any jsonb whatsoever. A generated column's
-- expression runs on every write *and* against every existing row when the
-- column is added, so an expression that raises on one odd legacy payload makes
-- that row unwritable and aborts this migration -- an availability incident in
-- the pipeline, not a caller's self-inflicted error. So it dispatches on
-- `jsonb_typeof` (which covers every possible node) rather than assuming a
-- shape, and it caps recursion depth instead of trusting the stack.
--
-- **Recursive, not two literal paths.** The obvious implementation removes
-- `run_state.sources[]` and `auto_resolved_checkpoint.snapshot.sources[]` and
-- stops. That is unsound because the worker is not the only writer: anything
-- with INSERT/UPDATE on `jobs.payload` decides the shape, so a body placed
-- anywhere else would survive. `RunState` (`state.py:229-247`) confirms
-- `sources[].cleaned_text` is the only whole-body field the *worker* writes;
-- the recursion exists for the writers that are not the worker. Do not
-- "simplify" this back to two paths.
--
-- Deliberately NOT `jsonb_strip_nulls`: that would remove legitimate nulls
-- elsewhere in `run_state` and silently change what the API reads. Exactly the
-- `cleaned_text` key goes, and nothing else -- array length, element order and
-- every sibling key are preserved.
--
-- `security definer` is not decoration and removing it breaks writes. The
-- generated column reaches the *outer* call by OID, so that call needs no
-- schema privilege — but the recursive call **inside** the body is resolved by
-- name at execution time, under the writing role. `service_role` holds no USAGE
-- on `private`, so an invoker-rights version fails
-- `permission denied for schema private` on every service-role insert into
-- `jobs`, and does so *intermittently*: plpgsql caches the compiled body per
-- backend, so a pooled connection that already ran this as `authenticated`
-- (which does hold USAGE) succeeds afterwards for anyone. Definer rights confer
-- nothing here — the function reads no table, runs no dynamic SQL, and touches
-- only its own argument — and the pinned `search_path` is the usual hygiene.
create or replace function private.strip_cleaned_text(p_node jsonb, p_depth integer)
returns jsonb
language plpgsql
immutable
parallel safe
security definer
set search_path = private, pg_temp
as $$
declare
    v_type text := jsonb_typeof(p_node);
    v_out  jsonb;
begin
    -- The only shape this function cannot represent losslessly. Postgres would
    -- otherwise raise `stack depth limit exceeded` here, and a raise is the one
    -- outcome a generated column cannot afford. Redacting the whole subtree
    -- fails closed. No worker payload is anywhere near this deep (RunState
    -- bottoms out around eight levels); nothing legitimate is truncated.
    if p_depth > 64 then
        return to_jsonb('[redacted: nesting depth]'::text);
    end if;

    if v_type = 'object' then
        select coalesce(
                   jsonb_object_agg(e.key, private.strip_cleaned_text(e.value, p_depth + 1)),
                   '{}'::jsonb)
          into v_out
          from jsonb_each(p_node) e
         where e.key <> 'cleaned_text';
        return v_out;
    elsif v_type = 'array' then
        select coalesce(
                   jsonb_agg(private.strip_cleaned_text(e.value, p_depth + 1) order by e.ord),
                   '[]'::jsonb)
          into v_out
          from jsonb_array_elements(p_node) with ordinality e(value, ord);
        return v_out;
    end if;

    -- string / number / boolean / json null, and SQL NULL (jsonb_typeof returns
    -- NULL, so v_type is NULL and neither branch is taken). Nothing to remove.
    return p_node;
end $$;

comment on function private.strip_cleaned_text(jsonb, integer) is
  'Returns its argument with every `cleaned_text` key removed at any depth. '
  'Total: never raises on any jsonb input, because it backs a generated column '
  'whose expression must not be able to make a row unwritable. Changing it '
  'does NOT recompute existing rows -- see the note on jobs.payload_public.';

-- ── 2. The maintained projection ─────────────────────────────────────────────
-- A generated column rather than a definer view or a worker-side strip:
--
--   * the *database* maintains it, so it is right for every writer -- including
--     any caller with direct INSERT/UPDATE on `jobs.payload`. A sanitization
--     the worker performs is bypassable by a writer that is not the worker;
--     one Postgres performs is not;
--   * no definer view, so there is no second copy of the `jobs_member_select`
--     RLS predicate to drift out of step with the original;
--   * backfill is automatic -- adding a STORED generated column computes it for
--     every existing row in the same statement.
--
-- Residual risk, stated here because it is not obvious: a generated column's
-- expression is **not** re-evaluated for existing rows when the function it
-- calls is later altered. `create or replace function private.strip_cleaned_text`
-- alone silently leaves every stored projection at the old semantics. Changing
-- the transform requires a deliberate column rebuild (drop and re-add the
-- column, or `update jobs set payload = payload`).
alter table jobs
    add column payload_public jsonb
    generated always as (private.strip_cleaned_text(payload, 0)) stored;

comment on column jobs.payload_public is
  'The member-readable projection of `payload`: identical, minus every '
  '`cleaned_text` key at any depth. `payload` itself is service-role only '
  '(DESIGN §16) -- `authenticated` holds SELECT on every column of this table '
  'EXCEPT that one. Every API read of a Job under a user JWT must name this '
  'column; `select *` on `jobs` is a hard permission denied.';

-- ── 3. The grants ────────────────────────────────────────────────────────────
-- Column-level REVOKE does nothing while a table-level SELECT grant stands --
-- the table grant simply wins. The only way to withhold one column is to drop
-- the table grant and re-grant the columns individually. Same shape as DM-1's
-- block for `property_sources`, and built dynamically for the same reason: a
-- hand-written column list would be correct today and quietly wrong after the
-- next `alter table ... add column`. The consequence is that a future column is
-- not granted until someone re-runs an equivalent statement, which fails closed
-- -- the new column is invisible rather than silently exposed.
--
-- `anon` is included even though no `jobs` policy names it, so that adding one
-- later cannot re-expose the bodies by accident.
do $$
declare
    v_cols text;
    v_role text;
begin
    select string_agg(quote_ident(column_name), ', ' order by ordinal_position)
      into v_cols
      from information_schema.columns
     where table_schema = 'public'
       and table_name   = 'jobs'
       and column_name <> 'payload';

    foreach v_role in array array['authenticated', 'anon'] loop
        execute format('revoke select on jobs from %I', v_role);
        execute format('grant select (%s) on jobs to %I', v_cols, v_role);
    end loop;
end $$;

-- ── Self-checks ──────────────────────────────────────────────────────────────
-- Supabase's bootstrap issues a blanket `grant select on all tables`, so a
-- future migration can silently undo the revoke above. That is the DM-1 pattern
-- and this is its third recurrence, so the assertion is written down rather
-- than assumed. `private.demo_preflight()` below carries the same check at
-- runtime, and `api/tests/test_jobs_payload_projection.py` carries it in CI.
do $$
begin
    if has_column_privilege('authenticated', 'public.jobs', 'payload', 'SELECT')
       or has_column_privilege('anon', 'public.jobs', 'payload', 'SELECT') then
        raise exception
            'jobs.payload is readable by authenticated/anon; it carries cleaned '
            'Source text, which DESIGN §16 requires be service-role only.';
    end if;
end $$;

-- The inverse: having dropped the table-level grant, every *other* column must
-- still be readable, or this migration has quietly broken the Tasks UI.
do $$
declare
    v_hidden text;
begin
    select string_agg(column_name, ', ' order by ordinal_position)
      into v_hidden
      from information_schema.columns
     where table_schema = 'public'
       and table_name   = 'jobs'
       and column_name <> 'payload'
       and not has_column_privilege('authenticated', 'public.jobs',
                                    column_name, 'SELECT');

    if v_hidden is not null then
        raise exception
            'These jobs columns lost their SELECT grant: %. '
            'Re-run the grant block in this migration.', v_hidden;
    end if;
end $$;

-- And the projection has to actually do its job on the rows that exist.
do $$
declare
    v_chars bigint;
begin
    select coalesce(sum(length(s.value ->> 'cleaned_text')), 0)
      into v_chars
      from jobs j,
           lateral jsonb_array_elements(
               coalesce(j.payload_public -> 'run_state' -> 'sources', '[]'::jsonb)) s;
    if v_chars > 0 then
        raise exception 'jobs.payload_public still carries % characters of page text', v_chars;
    end if;
end $$;

-- ── The runtime self-check ───────────────────────────────────────────────────
-- Recreated whole, as every migration in this series does, with one check
-- added. `demo_preflight` is the right home because a re-granted `payload` is
-- exactly the condition under which the demo must not be turned on -- but the
-- exposure it guards is not demo-specific, which is why the migration-time
-- assertion above and the CI test exist alongside it.
create or replace function private.demo_preflight()
returns text[]
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
    v_problems text[] := '{}';
    v_hunt uuid;
    v_demo uuid;
    v_list text;
begin
    select demo_hunt_id into v_hunt from site_settings;
    select user_id into v_demo from demo_accounts limit 1;

    if v_demo is null then
        v_problems := v_problems || 'no demo principal is configured'::text;
    end if;
    if v_hunt is null then
        v_problems := v_problems || 'site_settings.demo_hunt_id is null'::text;
    end if;

    select string_agg(c.relname, ', ' order by c.relname) into v_list
      from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind in ('r', 'p')
       and not exists (select 1 from pg_trigger t
                        where t.tgrelid = c.oid and t.tgname = 'demo_write_guard'
                          and not t.tgisinternal);
    if v_list is not null then
        v_problems := v_problems || ('tables without the write guard: ' || v_list)::text;
    end if;

    select string_agg(c.relname, ', ' order by c.relname) into v_list
      from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind = 'v'
       and (has_table_privilege('authenticated', c.oid, 'INSERT')
         or has_table_privilege('authenticated', c.oid, 'UPDATE')
         or has_table_privilege('authenticated', c.oid, 'DELETE'));
    if v_list is not null then
        v_problems := v_problems || ('views writable by authenticated: ' || v_list)::text;
    end if;

    if has_column_privilege('authenticated', 'public.property_sources',
                            'cleaned_text', 'SELECT') then
        v_problems := v_problems || 'property_sources.cleaned_text is readable'::text;
    end if;

    -- The second home of the same page text. `jobs` is member-selectable, so a
    -- re-granted `payload` publishes every cleaned Source body to the demo.
    if has_column_privilege('authenticated', 'public.jobs', 'payload', 'SELECT') then
        v_problems := v_problems || 'jobs.payload is readable'::text;
    end if;

    -- The principal must be virtual. An auth.users row would reintroduce the
    -- whole GoTrue takeover surface this design exists to remove.
    if v_demo is not null and exists (select 1 from auth.users where id = v_demo) then
        v_problems := v_problems
            || 'the demo principal has an auth.users row; it must be virtual'::text;
    end if;

    -- And it must hold no stored membership anywhere.
    if v_demo is not null and exists (select 1 from hunt_members where user_id = v_demo) then
        v_problems := v_problems
            || 'the demo principal holds a stored hunt membership'::text;
    end if;

    if v_hunt is not null and not exists (
        select 1 from hunts h
          join site_admins sa on sa.user_id = h.owner_id and sa.is_primordial
         where h.id = v_hunt)
    then
        v_problems := v_problems
            || 'the Demo Hunt is not owned by the primordial Site Admin'::text;
    end if;

    return v_problems;
end $$;

-- ── 4. The two RPCs that returned a whole Job row ────────────────────────────
-- A column revoke is not sufficient on its own. Column ACLs apply to *table
-- references*, not to composite rows returned by a function, and PostgREST
-- serialises every column of an RPC result -- so `returns setof jobs` on an
-- `authenticated`-executable `security definer` function hands the bodies
-- straight back regardless of the grants above. Both functions therefore return
-- an explicit projection whose `payload` column is fed from `payload_public`.
--
-- The column is still named `payload`, deliberately. `row_to_response` and
-- `answer_checkpoint` consume these rows; renaming the key would drop
-- `checkpoint` and `auto_resolved_checkpoint` from those responses *silently*
-- -- the Tasks UI would lose the prompt after answering, with no error anywhere.
-- Normalising at this boundary keeps one key name for every consumer.
--
-- Changing a function's return type needs `drop` + `create`; `create or replace`
-- refuses.

drop function if exists public.answer_job_checkpoint(uuid, jsonb, jsonb);

-- The parameter change is the second half of this fix, and it is the half that
-- prevents silent data loss.
--
-- With `payload` revoked, the API necessarily reads `payload_public`. The old
-- signature took a caller-supplied `p_payload` and **replaced** the column with
-- it, and the API's checkpoint answer was a read-modify-write: read the row,
-- mutate the parsed payload, send it back. Composed with the revoke that
-- round-trip would overwrite every stored payload with the body-free
-- projection, silently emptying every Source body -- silently because
-- `extract.py:336` skips an emptied Source rather than erroring, `verify.py:418`
-- audits evidence against "", and a later P3-11 correction Job is built from the
-- emptied snapshot.
--
-- So the function merges server-side against the row's own stored payload and
-- the caller supplies only the answer. The general rule the column list creates:
-- **no user-JWT or projection-sourced read may ever be written back to
-- `payload`.**
--
-- That also removes the injection primitive recorded in
-- `.claude/plans/checkpoint-payload-injection.md`: a member could previously
-- call this RPC directly with a payload of their choosing and steer the run at
-- another Property (via `property_id` or `sources[0].url`), or skip VERIFY
-- entirely via `plan`/`cursor`. There is no longer a parameter to do it with.
-- The answer's `choice` is validated **here** rather than only in the API,
-- because the RPC is directly callable through PostgREST and an API-side check
-- is therefore not a control.
create function public.answer_job_checkpoint(
    p_job_id uuid, p_answer jsonb, p_detail jsonb
)
returns table (
    id uuid,
    hunt_id uuid,
    hunt_listing_id uuid,
    type job_type,
    state job_state,
    current_stage text,
    plan jsonb,
    payload jsonb,
    attempts integer,
    error text,
    cost_actual_usd numeric(12,4),
    created_at timestamptz,
    started_at timestamptz,
    finished_at timestamptz,
    warnings jsonb
)
language plpgsql security definer set search_path = public
as $$
declare
    v_job jobs;
    v_role hunt_role;
    v_own boolean;
    v_prompt jsonb;
    v_choice text;
begin
    perform private.assert_not_demo('public.answer_job_checkpoint(uuid,jsonb,jsonb)');
    select * into v_job from jobs j where j.id = p_job_id for update;
    if not found or v_job.state <> 'waiting_user' then
        raise exception 'job is not waiting for a checkpoint' using errcode = '22023';
    end if;
    v_role := private.member_role(v_job.hunt_id);
    select exists (
        select 1 from hunt_listings hl
        where hl.id = v_job.hunt_listing_id and hl.added_by = auth.uid()
    ) into v_own;
    if v_role is null or (v_role = 'member' and not v_own) then
        raise exception 'checkpoint permission denied' using errcode = '42501';
    end if;

    -- The prompt comes from the stored row, never from the caller. `->` on a
    -- scalar or an array yields NULL rather than raising, so a malformed
    -- `run_state` lands here as "no checkpoint prompt".
    v_prompt := v_job.payload -> 'run_state' -> 'checkpoint';
    if v_prompt is null or jsonb_typeof(v_prompt) <> 'object' then
        raise exception 'job has no checkpoint prompt' using errcode = '22023';
    end if;

    if jsonb_typeof(p_answer) <> 'object' then
        raise exception 'invalid checkpoint answer' using errcode = '22023';
    end if;
    v_choice := p_answer ->> 'choice';
    -- `coalesce(..., false)`: `?` against a missing `options` yields NULL, and
    -- `if not null` is not a raise -- which would accept any choice at all.
    if v_choice is null
       or not coalesce((v_prompt -> 'options') ? v_choice, false) then
        raise exception 'invalid checkpoint answer' using errcode = '22023';
    end if;

    update jobs j
       set state = 'queued',
           payload = jsonb_set(
               jsonb_set(
                   jsonb_set(j.payload, '{run_state,status}', '"running"'::jsonb, true),
                   '{run_state,checkpoint}', 'null'::jsonb, true),
               '{checkpoint_answer}',
               p_answer || jsonb_build_object('context_ref', v_prompt -> 'context_ref'),
               true)
     where j.id = p_job_id
    returning * into v_job;

    insert into job_events (job_id, stage, event, detail)
    values (p_job_id, coalesce(v_job.current_stage, 'checkpoint'),
            'checkpoint_answered', p_detail);

    return query select
        v_job.id, v_job.hunt_id, v_job.hunt_listing_id, v_job.type, v_job.state,
        v_job.current_stage, v_job.plan, v_job.payload_public, v_job.attempts,
        v_job.error, v_job.cost_actual_usd, v_job.created_at, v_job.started_at,
        v_job.finished_at, v_job.warnings;
end;
$$;
revoke all on function public.answer_job_checkpoint(uuid, jsonb, jsonb) from public, anon;
grant execute on function public.answer_job_checkpoint(uuid, jsonb, jsonb) to authenticated;

comment on function public.answer_job_checkpoint(uuid, jsonb, jsonb) is
  'Applies a checkpoint answer by merging it into the Job''s own stored payload '
  'and re-queueing. The caller supplies the answer, never a RunState. Returns a '
  'body-free projection of the Job: `payload` is fed from `payload_public`, '
  'because a `setof jobs` return would bypass the column grants entirely.';

-- Same disclosure channel, same fix. This function is not injectable -- it
-- builds the new Job's payload from the stored snapshot -- but it inserts that
-- snapshot, a whole RunState with bodies, into the new Job and then returned the
-- row. `options`-missing is tightened to a refusal here too, for the reason
-- given above.
drop function if exists public.correct_auto_resolved_checkpoint(uuid, jsonb);

create function public.correct_auto_resolved_checkpoint(
    p_job_id uuid, p_answer jsonb
)
returns table (
    id uuid,
    hunt_id uuid,
    hunt_listing_id uuid,
    type job_type,
    state job_state,
    current_stage text,
    plan jsonb,
    payload jsonb,
    attempts integer,
    error text,
    cost_actual_usd numeric(12,4),
    created_at timestamptz,
    started_at timestamptz,
    finished_at timestamptz,
    warnings jsonb
)
language plpgsql security definer set search_path = public
as $$
declare
    v_job jobs;
    v_new_job jobs;
    v_role hunt_role;
    v_own boolean;
    v_meta jsonb;
    v_prompt jsonb;
    v_snapshot jsonb;
    v_choice text;
    v_new_id uuid := gen_random_uuid();
    v_payload jsonb;
begin
    perform private.assert_not_demo('public.correct_auto_resolved_checkpoint(uuid,jsonb)');
    select * into v_job from jobs j where j.id = p_job_id for update;
    if not found then
        raise exception 'job not found' using errcode = '22023';
    end if;
    if v_job.state not in ('done', 'failed') then
        raise exception 'auto-resolved checkpoint is still being applied'
            using errcode = '22023';
    end if;

    v_role := private.member_role(v_job.hunt_id);
    select exists (
        select 1 from hunt_listings hl
        where hl.id = v_job.hunt_listing_id and hl.added_by = auth.uid()
    ) into v_own;
    if v_role is null or (v_role = 'member' and not v_own) then
        raise exception 'checkpoint permission denied' using errcode = '42501';
    end if;

    v_meta := v_job.payload -> 'auto_resolved_checkpoint';
    v_prompt := v_meta -> 'prompt';
    v_snapshot := v_meta -> 'snapshot';
    if v_meta is null or v_prompt is null or v_snapshot is null then
        raise exception 'job has no auto-resolved checkpoint' using errcode = '22023';
    end if;
    if v_snapshot ->> 'job_id' is distinct from v_job.id::text
       or not exists (
           select 1 from job_events je
           where je.job_id = v_job.id and je.event = 'checkpoint_auto_resolved'
       ) then
        raise exception 'checkpoint correction provenance is invalid'
            using errcode = '22023';
    end if;
    if v_meta ? 'correction_job_id' then
        raise exception 'auto-resolved checkpoint was already corrected' using errcode = '22023';
    end if;

    v_choice := p_answer ->> 'choice';
    if v_choice is null
       or not coalesce((v_prompt -> 'options') ? v_choice, false) then
        raise exception 'invalid checkpoint answer' using errcode = '22023';
    end if;

    v_snapshot := jsonb_set(v_snapshot, '{job_id}', to_jsonb(v_new_id::text), true);
    v_snapshot := jsonb_set(v_snapshot, '{status}', '"running"'::jsonb, true);
    v_snapshot := jsonb_set(v_snapshot, '{checkpoint}', 'null'::jsonb, true);
    v_payload := (v_job.payload - 'checkpoint_answer' - 'auto_resolved_checkpoint')
        || jsonb_build_object(
            'run_state', v_snapshot,
            'checkpoint_answer', p_answer || jsonb_build_object(
                'context_ref', v_prompt -> 'context_ref'
            ),
            'trigger', 'user:checkpoint_correction',
            'corrects_job_id', v_job.id
        );

    insert into jobs (
        id, hunt_id, hunt_listing_id, type, state, plan, payload
    )
    values (
        v_new_id, v_job.hunt_id, v_job.hunt_listing_id, v_job.type,
        'queued', v_job.plan, v_payload
    )
    returning * into v_new_job;

    update jobs j
    set payload = jsonb_set(
        j.payload,
        '{auto_resolved_checkpoint}',
        v_meta || jsonb_build_object(
            'correction_job_id', v_new_id,
            'correction_answer', p_answer,
            'corrected_at', now()
        ),
        true
    )
    where j.id = v_job.id;

    insert into job_events (job_id, stage, event, detail)
    values (
        v_job.id,
        coalesce(v_job.current_stage, v_prompt ->> 'kind', 'checkpoint'),
        'checkpoint_answered',
        jsonb_build_object(
            'answer', p_answer,
            'late', true,
            'correction_job_id', v_new_id
        )
    );

    return query select
        v_new_job.id, v_new_job.hunt_id, v_new_job.hunt_listing_id, v_new_job.type,
        v_new_job.state, v_new_job.current_stage, v_new_job.plan,
        v_new_job.payload_public, v_new_job.attempts, v_new_job.error,
        v_new_job.cost_actual_usd, v_new_job.created_at, v_new_job.started_at,
        v_new_job.finished_at, v_new_job.warnings;
end;
$$;

revoke all on function public.correct_auto_resolved_checkpoint(uuid, jsonb)
    from public, anon;
grant execute on function public.correct_auto_resolved_checkpoint(uuid, jsonb)
    to authenticated;

comment on function public.correct_auto_resolved_checkpoint(uuid, jsonb) is
  'Creates the late-answer correction Job from the retained auto-resolved '
  'snapshot. Returns a body-free projection of the new Job for the same reason '
  'as answer_job_checkpoint: a `setof jobs` return bypasses column grants.';

notify pgrst, 'reload schema';
