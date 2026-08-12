"""Data API grants are explicit under Supabase CLI's opt-in exposure model."""

from __future__ import annotations


async def test_authenticated_can_reach_core_membership_tables(db_pool) -> None:
    """CLI >= 2.106 stops auto-granting; 20260901000023 restores the grants.

    Without them PostgREST fails with permission denied before RLS runs
    (collaboration-security / test_rls_matrix symptom).
    """
    missing = await db_pool.fetch(
        """
        select need.relname
          from (values
            ('hunts', 'SELECT'),
            ('hunt_members', 'SELECT'),
            ('visits', 'SELECT'),
            ('visits', 'INSERT')
          ) as need(relname, priv)
          join pg_class c on c.relname = need.relname
          join pg_namespace n on n.oid = c.relnamespace and n.nspname = 'public'
         where not has_table_privilege('authenticated', c.oid, need.priv)
         order by 1
        """
    )
    assert [r["relname"] for r in missing] == []


async def test_intentional_data_api_withholdings_still_hold(db_pool) -> None:
    assert not await db_pool.fetchval(
        "select has_column_privilege('authenticated', 'public.property_sources',"
        " 'cleaned_text', 'SELECT')"
    )
    assert not await db_pool.fetchval(
        "select has_column_privilege('authenticated', 'public.jobs', 'payload', 'SELECT')"
    )
    assert not await db_pool.fetchval(
        "select has_table_privilege('authenticated', 'public.worker_heartbeats', 'SELECT')"
    )


async def test_anonymous_postgrest_cannot_reach_public_relations(db_pool) -> None:
    """Manzil's unauthenticated surface is API/GoTrue, never table endpoints."""
    exposed = await db_pool.fetch(
        """
        select c.relname
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relkind in ('r', 'p', 'v', 'm', 'f')
           and (
               has_table_privilege('anon', c.oid, 'SELECT')
               or has_table_privilege('anon', c.oid, 'INSERT')
               or has_table_privilege('anon', c.oid, 'UPDATE')
               or has_table_privilege('anon', c.oid, 'DELETE')
           )
         order by c.relname
        """
    )
    assert [row["relname"] for row in exposed] == []


async def test_future_relations_require_own_data_api_grants(db_pool) -> None:
    """Do not reintroduce the legacy automatic public-schema exposure."""
    grants = await db_pool.fetch(
        """
        select d.defaclobjtype, acl.privilege_type
          from pg_default_acl d
          cross join lateral aclexplode(d.defaclacl)
            as acl(grantor, grantee, privilege_type, is_grantable)
         where d.defaclrole = 'postgres'::regrole
           and d.defaclnamespace = 'public'::regnamespace
           and d.defaclobjtype in ('r', 'S', 'f')
           and acl.grantee in (
               'anon'::regrole,
               'authenticated'::regrole,
               'service_role'::regrole,
               0
           )
        """
    )
    assert grants == []


async def test_service_role_can_execute_issue_demo_session(db_pool) -> None:
    """The one server-side demo RPC receives an explicit service-role grant."""
    assert await db_pool.fetchval(
        "select has_function_privilege('service_role',"
        " 'public.issue_demo_session(text, integer, integer)', 'EXECUTE')"
    )
    assert not await db_pool.fetchval(
        "select has_function_privilege('authenticated',"
        " 'public.issue_demo_session(text, integer, integer)', 'EXECUTE')"
    )
    assert not await db_pool.fetchval(
        "select has_function_privilege('anon',"
        " 'public.issue_demo_session(text, integer, integer)', 'EXECUTE')"
    )
    # This public user RPC must not acquire service access through an all-functions grant.
    assert not await db_pool.fetchval(
        "select has_function_privilege('service_role',"
        " 'public.set_hunt_archived(uuid, boolean)', 'EXECUTE')"
    )
