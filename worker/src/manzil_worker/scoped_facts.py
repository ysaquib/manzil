"""Central persistence/read seam for scoped Extractions (P3-SC2).

No caller may reconstruct "latest per Criterion" itself. Current reads come
from the security-invoker views; writes always append candidate + resolved rows
and the provenance edge in one transaction owned by the caller.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from manzil_shared.models import Confidence, TargetScope, UnitApplicability
from manzil_shared.scoped_facts import ScopedOverrideValue, ScopedValue

from manzil_worker.state import SourceClaim


def _json_value(raw: Any) -> Any:
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


async def append_candidate_resolution(
    conn: asyncpg.Connection,
    *,
    property_id: UUID,
    hunt_id: UUID | None,
    criterion_key: str,
    value: Any,
    confidence: Confidence,
    evidence_quote: str | None,
    source_id: UUID | None,
    origin_key: str,
    target_scope: TargetScope,
    floor_plan_id: UUID | None,
    applicability: UnitApplicability | None,
    claim_group_id: UUID,
    model: str,
    job_id: UUID | None,
    resolution_rule: str = "single_source",
    disputed: bool = False,
) -> tuple[UUID, UUID]:
    """Append one candidate, its one-Source resolution, and lineage edge."""
    candidate_id: UUID = await conn.fetchval(
        """
        insert into extractions
            (property_id, hunt_id, criterion_key, record_kind, origin_key, source_id,
             target_scope, floor_plan_id, applicability, claim_group_id, value,
             confidence, evidence_quote, model, job_id)
        values
            ($1, $2, $3, 'candidate', $4, $5, $6, $7, $8, $9,
             $10::jsonb, $11::confidence, $12, $13, $14)
        returning id
        """,
        property_id,
        hunt_id,
        criterion_key,
        origin_key,
        source_id,
        target_scope.value,
        floor_plan_id,
        applicability.value if applicability is not None else None,
        claim_group_id,
        json.dumps(value),
        confidence.value,
        evidence_quote,
        model,
        job_id,
    )
    resolution_group_id = uuid4()
    resolution_id: UUID = await conn.fetchval(
        """
        insert into extractions
            (property_id, hunt_id, criterion_key, record_kind, origin_key,
             target_scope, floor_plan_id, applicability, claim_group_id, value,
             confidence, evidence_quote, model, resolution_rule, disputed, job_id)
        values
            ($1, $2, $3, 'resolved', $4, $5, $6, $7, $8, $9::jsonb,
             $10::confidence, $11, $12, $13, $14, $15)
        returning id
        """,
        property_id,
        hunt_id,
        criterion_key,
        f"resolution:{job_id or resolution_group_id}",
        target_scope.value,
        floor_plan_id,
        applicability.value if applicability is not None else None,
        resolution_group_id,
        json.dumps(value),
        confidence.value,
        evidence_quote,
        model,
        resolution_rule,
        disputed,
        job_id,
    )
    await conn.execute(
        """
        insert into extraction_resolution_candidates
            (resolution_extraction_id, candidate_extraction_id, selected)
        values ($1, $2, true)
        """,
        resolution_id,
        candidate_id,
    )
    return candidate_id, resolution_id


async def persist_single_source_claims(
    conn: asyncpg.Connection,
    *,
    property_id: UUID,
    hunt_id: UUID | None,
    source_id: UUID,
    source_url: str,
    job_id: UUID | None,
    claims: Iterable[SourceClaim],
    floor_plan_ids_by_ref: Mapping[str, UUID],
    authoritative: bool = False,
) -> None:
    """Resolve response-local refs, validate target shape, and append facts.

    A complete successful Source refresh is authoritative for that Source's
    prior claim identities. Any identity omitted by the new response gets an
    explicit not-found version. Partial/failed work passes ``authoritative=False``
    and therefore cannot retire truth by silence.
    """
    prior_rows = []
    if authoritative:
        prior_rows = await conn.fetch(
            """
            select criterion_key, target_scope, floor_plan_id, applicability, confidence
            from current_extraction_candidates
            where property_id = $1 and hunt_id is not distinct from $2 and source_id = $3
            """,
            property_id,
            hunt_id,
            source_id,
        )

    observed: set[tuple[str, TargetScope, UUID | None]] = set()
    materialized_claims = list(claims)
    for claim in materialized_claims:
        floor_plan_id = claim.floor_plan_id
        if claim.floor_plan_ref is not None:
            floor_plan_id = floor_plan_ids_by_ref.get(claim.floor_plan_ref)
            if floor_plan_id is None:
                raise ValueError(
                    f"claim {claim.criterion_key!r} references unknown Source-local "
                    f"Floor Plan {claim.floor_plan_ref!r}"
                )
        if claim.target_scope is TargetScope.FLOOR_PLAN:
            if (
                floor_plan_id is None
                or claim.applicability is not UnitApplicability.SPECIFIC_FLOOR_PLANS
            ):
                raise ValueError(
                    "exact Floor Plan claim requires a resolved target and exact applicability"
                )
        elif floor_plan_id is not None:
            raise ValueError("Property-target claim cannot carry floor_plan_id")

        observed.add((claim.criterion_key, claim.target_scope, floor_plan_id))

        from_page = claim.source_id == source_url
        producer_origin = claim.origin_key or claim.source_id or claim.model
        await append_candidate_resolution(
            conn,
            property_id=property_id,
            hunt_id=hunt_id,
            criterion_key=claim.criterion_key,
            value=claim.value,
            confidence=claim.confidence,
            evidence_quote=claim.evidence_quote,
            source_id=source_id if from_page else None,
            origin_key=(f"property_source:{source_id}" if from_page else producer_origin),
            target_scope=claim.target_scope,
            floor_plan_id=floor_plan_id,
            applicability=claim.applicability,
            claim_group_id=claim.claim_group_id,
            model=claim.model,
            job_id=job_id,
            resolution_rule=claim.resolution_rule or "single_source",
            disputed=claim.disputed,
        )

    if not authoritative:
        return
    refresh_model = materialized_claims[0].model if materialized_claims else "authoritative_refresh"
    for row in prior_rows:
        target_scope = TargetScope(row["target_scope"])
        identity = (row["criterion_key"], target_scope, row["floor_plan_id"])
        if identity in observed or row["confidence"] == Confidence.NOT_FOUND.value:
            continue
        applicability = (
            UnitApplicability(row["applicability"]) if row["applicability"] is not None else None
        )
        await append_candidate_resolution(
            conn,
            property_id=property_id,
            hunt_id=hunt_id,
            criterion_key=row["criterion_key"],
            value=None,
            confidence=Confidence.NOT_FOUND,
            evidence_quote=None,
            source_id=source_id,
            origin_key=f"property_source:{source_id}",
            target_scope=target_scope,
            floor_plan_id=row["floor_plan_id"],
            applicability=applicability,
            claim_group_id=uuid4(),
            model=refresh_model,
            job_id=job_id,
            resolution_rule="source_refresh_not_found",
        )


async def load_current_extractions(
    conn: asyncpg.Connection,
    *,
    property_id: UUID,
    hunt_id: UUID,
) -> list[ScopedValue]:
    rows = await conn.fetch(
        """
        select criterion_key, value, confidence, target_scope, floor_plan_id,
               applicability, extracted_at
        from current_extractions
        where property_id = $1 and (hunt_id is null or hunt_id = $2)
        """,
        property_id,
        hunt_id,
    )
    return [
        ScopedValue(
            criterion_key=row["criterion_key"],
            value=_json_value(row["value"]),
            confidence=Confidence(row["confidence"]),
            target_scope=TargetScope(row["target_scope"]),
            floor_plan_id=row["floor_plan_id"],
            applicability=(
                UnitApplicability(row["applicability"])
                if row["applicability"] is not None
                else None
            ),
            observed_at=row["extracted_at"],
        )
        for row in rows
    ]


async def load_current_overrides(
    conn: asyncpg.Connection, *, hunt_listing_id: UUID
) -> list[ScopedOverrideValue]:
    rows = await conn.fetch(
        """
        select criterion_key, value, target_scope, floor_plan_id, applicability, created_at
        from current_overrides
        where hunt_listing_id = $1
        """,
        hunt_listing_id,
    )
    return [
        ScopedOverrideValue(
            criterion_key=row["criterion_key"],
            value=_json_value(row["value"]),
            target_scope=TargetScope(row["target_scope"]),
            floor_plan_id=row["floor_plan_id"],
            applicability=(
                UnitApplicability(row["applicability"])
                if row["applicability"] is not None
                else None
            ),
            created_at=row["created_at"],
        )
        for row in rows
    ]


def property_values(rows: Iterable[ScopedValue]) -> dict[str, tuple[Any, Confidence]]:
    """Property-target resolved values for non-Rubric composition consumers."""
    return {
        row.criterion_key: (row.value, row.confidence)
        for row in rows
        if row.target_scope is TargetScope.PROPERTY and row.applicability is None
    }
