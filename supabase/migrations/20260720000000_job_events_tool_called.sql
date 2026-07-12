-- P3-3: agent tool loops (§10.2) log every tool invocation + result as a
-- job_events row. Extend the `event` check constraint (from 20260708) with the
-- new `tool_called` value so the Tasks history can render "searched X, fetched Y".
-- The inline column check in 20260708 is auto-named `job_events_event_check`.

alter table job_events drop constraint job_events_event_check;

alter table job_events add constraint job_events_event_check check (
    event in (
        'started', 'completed', 'failed', 'checkpoint_asked',
        'checkpoint_answered', 'checkpoint_auto_resolved', 'escalated_tier',
        'tool_called'
    )
);
