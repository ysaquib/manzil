"""P3-SC3 versioned development Rubric and drift-safe installer."""

from __future__ import annotations

import os

import asyncpg
import pytest
from manzil_worker.dev_rubric import (
    DEV_RUBRIC_HUNT_ID,
    DevRubricDriftError,
    install_dev_rubric,
    load_dev_rubric,
    verify_dev_rubric_goldens,
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)


def test_dev_rubric_fixture_is_versioned_gate_free_and_golden() -> None:
    template = load_dev_rubric()
    assert template.template_version == 1
    assert {criterion.catalog_key for criterion in template.criteria} >= {
        "pool",
        "fitness_center",
        "clubhouse",
        "smoking_policy",
        "property_types",
        "unit_types",
        "internet_readiness",
    }
    assert all(
        option.dealbreaker_set_score is None
        for criterion in template.criteria
        for option in criterion.options
    )
    assert all(criterion.non_negotiable is None for criterion in template.rubric())
    verify_dev_rubric_goldens(template)


@pytest.mark.asyncio
async def test_dev_rubric_installer_noops_and_refuses_local_drift() -> None:
    try:
        conn = await asyncpg.connect(DATABASE_URL, timeout=5)
    except (OSError, asyncpg.PostgresError) as error:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {error}")
    try:
        await conn.execute("delete from hunts where id = $1", DEV_RUBRIC_HUNT_ID)
        async with conn.transaction():
            first = await install_dev_rubric(conn)
        assert first.status == "installed"

        jobs_after_install = await conn.fetchval(
            "select count(*) from jobs where hunt_id = $1 and type = 'rescore'",
            DEV_RUBRIC_HUNT_ID,
        )
        async with conn.transaction():
            second = await install_dev_rubric(conn)
        assert second.status == "unchanged"
        assert (
            await conn.fetchval(
                "select count(*) from jobs where hunt_id = $1 and type = 'rescore'",
                DEV_RUBRIC_HUNT_ID,
            )
            == jobs_after_install
        )

        await conn.execute(
            """
            update rubric_criteria set unknown_delta = -0.5
            where hunt_id = $1 and catalog_key = 'pool'
            """,
            DEV_RUBRIC_HUNT_ID,
        )
        with pytest.raises(DevRubricDriftError, match="--force"):
            async with conn.transaction():
                await install_dev_rubric(conn)

        async with conn.transaction():
            forced = await install_dev_rubric(conn, force=True)
        assert forced.status == "installed"
        assert (
            await conn.fetchval(
                """
            select unknown_delta from rubric_criteria
            where hunt_id = $1 and catalog_key = 'pool'
            """,
                DEV_RUBRIC_HUNT_ID,
            )
            == 0
        )
    finally:
        await conn.execute("delete from hunts where id = $1", DEV_RUBRIC_HUNT_ID)
        await conn.close()
