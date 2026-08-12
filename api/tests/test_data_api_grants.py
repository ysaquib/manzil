"""Data API table grants survive CLI auto_expose_new_tables=false."""

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


async def test_service_role_can_execute_issue_demo_session(db_pool) -> None:
    """CLI >= 2.106 drops default EXECUTE; 20260901000024 restores it."""
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
