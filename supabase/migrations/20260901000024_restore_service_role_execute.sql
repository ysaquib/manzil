-- Restore service_role EXECUTE after Supabase CLI >= 2.106.
--
-- The same auto_expose flip that dropped table GRANTs also stops granting
-- EXECUTE on new public/private functions to service_role. Several SECURITY
-- DEFINER RPCs (notably issue_demo_session) intentionally REVOKE from
-- public/anon/authenticated and relied on the bootstrap service_role grant.
-- Without it PostgREST returns 42501 before the function body runs.

alter default privileges for role postgres in schema public
    grant execute on functions to service_role;

alter default privileges for role postgres in schema private
    grant execute on functions to service_role;

grant execute on all functions in schema public to service_role;
grant execute on all functions in schema private to service_role;

-- Self-check: the demo session RPC the API calls with the service role.
do $$
begin
    if not has_function_privilege(
        'service_role',
        'public.issue_demo_session(text, integer, integer)',
        'EXECUTE'
    ) then
        raise exception
            'service_role lacks EXECUTE on issue_demo_session; '
            'POST /v1/demo/session will 500 under CLI >= 2.106';
    end if;
    if has_function_privilege(
        'authenticated',
        'public.issue_demo_session(text, integer, integer)',
        'EXECUTE'
    ) or has_function_privilege(
        'anon',
        'public.issue_demo_session(text, integer, integer)',
        'EXECUTE'
    ) then
        raise exception
            'issue_demo_session must stay unreachable to anon/authenticated';
    end if;
end $$;
