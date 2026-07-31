-- P3-11: late answers preserve the auto-resolved Job's immutable history.
--
-- The worker stores the pre-default RunState under
-- payload.auto_resolved_checkpoint.snapshot. A late answer creates a fresh Job
-- from that exact Stage boundary; it never rewinds the completed Job's cursor.

create or replace function public.correct_auto_resolved_checkpoint(
    p_job_id uuid, p_answer jsonb
)
returns setof jobs
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
    select * into v_job from jobs where id = p_job_id for update;
    if not found then
        raise exception 'job not found' using errcode = '22023';
    end if;
    if v_job.state not in ('done', 'failed') then
        raise exception 'auto-resolved checkpoint is still being applied'
            using errcode = '22023';
    end if;

    v_role := private.member_role(v_job.hunt_id);
    select exists (
        select 1 from hunt_listings
        where id = v_job.hunt_listing_id and added_by = auth.uid()
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
           select 1 from job_events
           where job_id = v_job.id and event = 'checkpoint_auto_resolved'
       ) then
        raise exception 'checkpoint correction provenance is invalid'
            using errcode = '22023';
    end if;
    if v_meta ? 'correction_job_id' then
        raise exception 'auto-resolved checkpoint was already corrected' using errcode = '22023';
    end if;

    v_choice := p_answer ->> 'choice';
    if v_choice is null or not ((v_prompt -> 'options') ? v_choice) then
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

    update jobs
    set payload = jsonb_set(
        payload,
        '{auto_resolved_checkpoint}',
        v_meta || jsonb_build_object(
            'correction_job_id', v_new_id,
            'correction_answer', p_answer,
            'corrected_at', now()
        ),
        true
    )
    where id = v_job.id;

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

    return next v_new_job;
end;
$$;

revoke all on function public.correct_auto_resolved_checkpoint(uuid, jsonb)
    from public, anon;
grant execute on function public.correct_auto_resolved_checkpoint(uuid, jsonb)
    to authenticated;
