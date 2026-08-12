-- Product email is strictly opt-in. Existing account and Hunt preference rows
-- remain explicit choices; only missing rows resolve to disabled.

create or replace function private.notification_default_enabled(p_event_type text)
returns boolean language sql immutable as $$
    select false
$$;

revoke all on function private.notification_default_enabled(text)
    from public, anon, authenticated;
