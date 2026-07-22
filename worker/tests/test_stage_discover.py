"""P3-5 DISCOVER stage: identity filtering, policy caps, and slate diversity."""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from uuid import uuid4

import pytest
from manzil_shared.errors import AgentBudgetExceeded, StageRetryable
from manzil_shared.models import JobType
from manzil_worker.discovery_sources import SOURCE_METADATA
from manzil_worker.fetching.registry import InMemoryRegistry
from manzil_worker.llm.tools import AgentResult
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.discover import discover_stage
from manzil_worker.state import PlanManifest, PlanSource, PropertyIdentityIn, RunState

SUBMITTED = "https://www.apartments.com/maple-court-detroit-mi/abc123/"
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_source_metadata_matches_the_hostile_domain_census() -> None:
    with (REPO_ROOT / "docs" / "hostile-domain-census.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert set(SOURCE_METADATA) == {row["site_domain"] for row in rows}
    for row in rows:
        metadata = SOURCE_METADATA[row["site_domain"]]
        assert metadata.census_tier == int(row["required_tier"])
        assert metadata.syndication_family == row["syndication_family"]


def _state(policy: str = "tiers_1_2_3") -> RunState:
    return RunState(
        job_id=uuid4(),
        job_type=JobType.INGEST,
        url=SUBMITTED,
        source_policy=policy,
        property_identity=PropertyIdentityIn(
            name="Maple Court Apartments",
            address="120 Maple Court Dr, Detroit, MI 48201",
        ),
        plan=PlanManifest(
            job_type="ingest",
            trigger="user:submit",
            source_policy=policy,
            sources=[PlanSource(url=SUBMITTED, action="fetch", tier=3)],
            stages=["DISCOVER"],
            skipped={},
            est_cost_usd=0.04,
        ),
    )


def _agent(payload: dict[str, object]):  # type: ignore[no-untyped-def]
    async def call(stage, task, tools, max_turns):  # type: ignore[no-untyped-def]
        assert stage == "discover"
        assert max_turns > 0
        assert [tool.__name__ for tool in tools] == ["fetch_page"]
        assert "Maple Court Apartments" in task
        return AgentResult(final_text=json.dumps(payload), turns=1)

    return call


def _candidate(url: str, *, confidence: str = "high", same: bool = True) -> dict[str, object]:
    return {
        "url": url,
        "same_property": same,
        "confidence": confidence,
        "evidence": "same street address and property name",
    }


def test_builds_family_distinct_tier_slate_and_retains_official_link() -> None:
    payload = {
        "official_url": "https://maplecourt.example/",
        "official_confidence": "high",
        "official_evidence": "official site has the same address",
        "candidates": [
            _candidate("https://www.rent.com/michigan/detroit-apartments/maple-court"),
            _candidate("https://hotpads.com/maple-court-detroit-mi/test"),
            # Same family as HotPads and unnecessary because submitted source is tier 3.
            _candidate("https://www.trulia.com/building/maple-court-detroit-mi"),
            _candidate("https://example.test/wrong-building", same=False),
            _candidate("https://rentberry.com/maple-court", confidence="low"),
        ],
    }
    state = _state()
    out = asyncio.run(
        discover_stage(
            state,
            StageCtx(
                call_agent=_agent(payload),
                registry=InMemoryRegistry(),
                fetchers={1: object(), 2: object(), 3: object()},  # type: ignore[dict-item]
            ),
        )
    )

    assert out.official_source_url == "https://maplecourt.example/"
    official = next(source for source in out.discovered_sources if source.is_official)
    assert official.selection_reason == "official_arbiter_only"
    assert official.selected_for_slate is False
    selected = [source for source in out.discovered_sources if source.selected_for_slate]
    assert {(source.required_tier, source.syndication_family) for source in selected} == {
        (1, "rent_group"),
        (2, "zillow"),
    }
    assert out.slate_urls == [SUBMITTED, *(source.url for source in selected)]
    assert out.single_source_reason is None
    assert any(
        source.action == "skip" and source.why == "official_arbiter_only"
        for source in out.plan.sources  # type: ignore[union-attr]
    )
    assert all("wrong-building" not in source.url for source in out.discovered_sources)
    assert all("rentberry" not in source.url for source in out.discovered_sources)


def test_policy_cap_records_over_cap_sources_without_fetching_them() -> None:
    state = _state("tier_1")
    out = asyncio.run(
        discover_stage(
            state,
            StageCtx(
                call_agent=_agent(
                    {
                        "candidates": [
                            _candidate("https://rent.com/maple-court"),
                            _candidate("https://hotpads.com/maple-court"),
                            _candidate("https://zillow.com/maple-court"),
                        ]
                    }
                ),
                registry=InMemoryRegistry(),
                fetchers={1: object(), 2: object(), 3: object()},  # type: ignore[dict-item]
            ),
        )
    )

    assert len([source for source in out.discovered_sources if source.selected_for_slate]) == 1
    assert any(
        source.action == "skip" and source.why == "policy_tier_cap"
        for source in out.plan.sources  # type: ignore[union-attr]
    )


def test_missing_tier_uses_a_cheaper_family_distinct_substitute() -> None:
    state = _state()
    out = asyncio.run(
        discover_stage(
            state,
            StageCtx(
                call_agent=_agent(
                    {
                        "candidates": [
                            _candidate("https://rent.com/maple-court"),
                            _candidate("https://apartmentlist.com/maple-court"),
                        ]
                    }
                ),
                registry=InMemoryRegistry(),
                fetchers={1: object(), 2: object(), 3: object()},  # type: ignore[dict-item]
            ),
        )
    )

    selected = [source for source in out.discovered_sources if source.selected_for_slate]
    assert {source.selection_reason for source in selected} == {
        "tier_1_slot",
        "substitute_for_tier_2",
    }


def test_tier_three_candidate_skips_when_provider_is_unavailable() -> None:
    state = _state("tiers_1_2_3")
    # Make the submitted domain tier 1 so the policy has tier 2 and 3 slots.
    state.url = "https://rent.com/maple-court"
    state.plan.sources[0].url = state.url  # type: ignore[union-attr]
    out = asyncio.run(
        discover_stage(
            state,
            StageCtx(
                call_agent=_agent({"candidates": [_candidate("https://zillow.com/maple-court")]}),
                registry=InMemoryRegistry(),
                fetchers={1: object(), 2: object()},  # type: ignore[dict-item]
            ),
        )
    )

    assert out.slate_urls == [state.url]
    assert out.single_source_reason == "discover_exhausted"
    assert out.plan.sources[-1].why == "tier_unavailable"  # type: ignore[union-attr]


def test_no_siblings_is_a_successful_single_source_outcome() -> None:
    out = asyncio.run(
        discover_stage(
            _state(),
            StageCtx(call_agent=_agent({"candidates": []}), registry=InMemoryRegistry()),
        )
    )
    assert out.slate_urls == [SUBMITTED]
    assert out.single_source_reason == "discover_exhausted"


def test_budget_failure_degrades_honestly_without_claiming_search_exhaustion() -> None:
    async def exhausted(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AgentBudgetExceeded("turn budget exhausted")

    out = asyncio.run(
        discover_stage(_state(), StageCtx(call_agent=exhausted, registry=InMemoryRegistry()))
    )
    assert out.slate_urls == [SUBMITTED]
    assert out.single_source_reason == "discover_failed"
    assert out.discover_error == "turn budget exhausted"


def test_malformed_final_answer_is_retryable() -> None:
    async def malformed(*args, **kwargs):  # type: ignore[no-untyped-def]
        return AgentResult(final_text="not json", turns=1)

    with pytest.raises(StageRetryable, match="invalid final JSON"):
        asyncio.run(
            discover_stage(_state(), StageCtx(call_agent=malformed, registry=InMemoryRegistry()))
        )


def test_prefaced_fenced_json_is_accepted() -> None:
    async def prefaced(*args, **kwargs):  # type: ignore[no-untyped-def]
        return AgentResult(
            final_text='I found the result.\n```json\n{"candidates": []}\n```',
            turns=1,
        )

    out = asyncio.run(
        discover_stage(_state(), StageCtx(call_agent=prefaced, registry=InMemoryRegistry()))
    )
    assert out.single_source_reason == "discover_exhausted"


def test_more_than_three_candidates_uses_plan_assist_ranking() -> None:
    ordered = [
        "https://rentberry.com/maple-court",
        "https://rent.com/maple-court",
        "https://rentable.co/maple-court",
        "https://apartmentlist.com/maple-court",
    ]
    calls: list[str] = []

    async def rank(stage, schema, content):  # type: ignore[no-untyped-def]
        calls.append(stage)
        return schema.model_validate({"ordered_urls": ordered})

    payload = {"candidates": [_candidate(url) for url in reversed(ordered)]}
    out = asyncio.run(
        discover_stage(
            _state(),
            StageCtx(
                call_agent=_agent(payload),
                call_structured=rank,
                registry=InMemoryRegistry(),
                fetchers={1: object(), 2: object(), 3: object()},  # type: ignore[dict-item]
            ),
        )
    )

    assert calls == ["plan_assist"]
    ranked = [source.url for source in out.discovered_sources if not source.is_official]
    assert ranked == ordered


def test_defensive_trust_link_branch_never_calls_agent() -> None:
    async def forbidden(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("DISCOVER must not call the agent")

    out = asyncio.run(discover_stage(_state("trust_link"), StageCtx(call_agent=forbidden)))
    assert out.single_source_reason == "trust_link"
    assert out.slate_urls == [SUBMITTED]
