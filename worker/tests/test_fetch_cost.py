"""AD-C: non-LLM spend is real spend.

Tier-3 requests cost money ($0.0015 each, 5,000 credits a month on the free
plan) and were invisible before this: the tally was token-shaped, so a Hunt
fetching through hostile domains under-reported its bill. These tests pin the
whole path — pricing, the fetcher's recording point, the runner's folding, and
the per-stage breakdown.

No live unblocker calls: httpx.MockTransport plays the vendor, as in
test_tier3.py.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import httpx
import pytest
from manzil_shared.errors import FetchProviderError, StageRetryable
from manzil_shared.models import JobType
from manzil_worker.costs import CostTally, active_tally, cost_tally, record_fetch
from manzil_worker.fetching.tier3 import Tier3Fetcher
from manzil_worker.runner import run_job
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState

LISTING_HTML = "<html><body>" + "2 bedroom apartment with rent. " * 60 + "</body></html>"


async def _public_resolver(host: str) -> list[str]:
    """Every host resolves public so the tier-3 SSRF screen passes offline."""
    return ["93.184.216.34"]


class RecordingPersistence:
    async def save(self, state: RunState) -> None:  # pragma: no cover - trivial
        return None


def make_ctx() -> StageCtx:
    async def fake_sleep(seconds: float) -> None:
        return None

    return StageCtx(persistence=RecordingPersistence(), sleep=fake_sleep)


def make_state() -> RunState:
    return RunState(job_id=uuid4(), job_type=JobType.INGEST, url="https://x.test/1")


# ── pricing ──────────────────────────────────────────────────────────────────


def test_brightdata_calls_are_priced_at_the_published_rate() -> None:
    tally = CostTally()
    tally.add_fetch("brightdata")
    tally.add_fetch("brightdata", calls=3)

    assert tally.fetch_calls == 4
    assert tally.fetch_cost_usd == pytest.approx(0.006)  # 4 x $0.0015
    assert tally.fetch_calls_by_provider == {"brightdata": 4}


def test_an_unpriced_provider_is_counted_but_never_guessed_at() -> None:
    """Counting without pricing is honest; inventing a price is not. The gap
    shows up as calls > 0 with cost == 0 rather than as silently-free traffic."""
    tally = CostTally()
    tally.add_fetch("scrapingbee", calls=2)

    assert tally.fetch_calls == 2
    assert tally.fetch_cost_usd == 0.0
    assert tally.fetch_calls_by_provider == {"scrapingbee": 2}


def test_total_keeps_the_two_channels_separable() -> None:
    """A blended number cannot answer "how much of this was the model?"."""
    tally = CostTally(cost_usd=0.04)
    tally.add_fetch("brightdata", calls=2)

    assert tally.cost_usd == 0.04  # token spend, untouched by fetching
    assert tally.fetch_cost_usd == pytest.approx(0.003)
    assert tally.total_cost_usd == pytest.approx(0.043)


def test_record_fetch_is_a_no_op_outside_a_stage() -> None:
    assert active_tally() is None
    record_fetch("brightdata")  # must not raise


# ── the fetcher's recording point ────────────────────────────────────────────


def _brightdata_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MANZIL_TIER3_PROVIDER", raising=False)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-key")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "my_zone")


def _envelope(status: int, body: str) -> httpx.Response:
    return httpx.Response(200, json={"status": status, "headers": {}, "body": body})


def test_tier3_bills_a_request_that_gets_a_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _brightdata_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return _envelope(200, LISTING_HTML)

    fetcher = Tier3Fetcher(transport=httpx.MockTransport(handler), resolver=_public_resolver)
    with cost_tally() as tally:
        result = asyncio.run(fetcher.fetch("https://www.zillow.com/detroit-mi/rentals/"))

    assert result.status_code == 200
    assert tally.fetch_calls == 1
    assert tally.fetch_cost_usd == pytest.approx(0.0015)


def test_tier3_bills_a_blocked_page_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """The provider ran the request and charged for it whatever the target said;
    a 403 that costs a credit must not read as free."""
    _brightdata_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return _envelope(403, "Access denied")

    fetcher = Tier3Fetcher(transport=httpx.MockTransport(handler), resolver=_public_resolver)
    with cost_tally() as tally:
        result = asyncio.run(fetcher.fetch("https://www.zillow.com/detroit-mi/rentals/"))

    assert result.status_code == 403
    assert tally.fetch_calls == 1


def test_tier3_does_not_bill_a_request_that_never_landed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transport failure means the provider never ran anything. Billing it
    would drain the credit meter on our own network problems."""
    _brightdata_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    fetcher = Tier3Fetcher(transport=httpx.MockTransport(handler), resolver=_public_resolver)
    with cost_tally() as tally:
        result = asyncio.run(fetcher.fetch("https://www.zillow.com/detroit-mi/rentals/"))

    assert result.error is not None
    assert tally.fetch_calls == 0
    assert tally.fetch_cost_usd == 0.0


def test_tier3_does_not_bill_a_request_the_provider_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected zone/key/balance never reached the target, so it is not a
    fetch. Billing it inflates the very meter an operator reads to ask whether
    the plan ran out — the 2026-08-11 incident charged itself 12 phantom
    credits while diagnosing itself."""
    _brightdata_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Unknown zone")

    fetcher = Tier3Fetcher(transport=httpx.MockTransport(handler), resolver=_public_resolver)
    with cost_tally() as tally, pytest.raises(FetchProviderError):
        asyncio.run(fetcher.fetch("https://www.zillow.com/detroit-mi/rentals/"))

    assert tally.fetch_calls == 0
    assert tally.fetch_cost_usd == 0.0


# ── the runner folds it onto the job ─────────────────────────────────────────


def test_fetch_spend_reaches_the_job_total_and_the_stage_breakdown() -> None:
    async def spendy_stage(state: RunState, ctx: StageCtx) -> RunState:
        record_fetch("brightdata", calls=2)
        return state

    state = asyncio.run(run_job(make_state(), make_ctx(), stages=[("fetch", spendy_stage)]))

    assert state.cost_usd == pytest.approx(0.003)
    assert [row.stage for row in state.stage_costs] == ["fetch"]
    row = state.stage_costs[0]
    assert row.fetch_calls == 2
    assert row.fetch_cost_usd == pytest.approx(0.003)
    assert row.llm_cost_usd == 0.0
    assert row.fetch_calls_by_provider == {"brightdata": 2}


def test_a_retried_stage_keeps_the_spend_of_its_failed_attempts() -> None:
    """The old behaviour dropped everything a failed attempt burned: each retry
    opened a fresh tally and only the winning one was counted. Two blocked
    fetches followed by a success cost three credits, not one."""
    attempts = {"n": 0}

    async def flaky_stage(state: RunState, ctx: StageCtx) -> RunState:
        attempts["n"] += 1
        record_fetch("brightdata")
        if attempts["n"] < 3:
            raise StageRetryable("blocked, escalating")
        return state

    state = asyncio.run(run_job(make_state(), make_ctx(), stages=[("fetch", flaky_stage)]))

    assert attempts["n"] == 3
    assert state.cost_usd == pytest.approx(0.0045)  # 3 x $0.0015
    assert state.stage_costs[0].fetch_calls == 3


def test_a_stage_that_re_runs_replaces_its_row_rather_than_doubling_it() -> None:
    """Breakdown rows are replace-semantics (same posture as warnings), so a
    resumed job reports what the latest run of each stage cost."""
    state = make_state()
    tally = CostTally()
    tally.add_fetch("brightdata", calls=4)
    state.record_stage_cost("fetch", tally)
    state.record_stage_cost("fetch", tally)

    assert len(state.stage_costs) == 1
    assert state.stage_costs[0].fetch_calls == 4


def test_pre_ad_c_snapshots_still_validate() -> None:
    """`stage_costs` is optional-with-default, so every parked job and recorded
    fixture written before AD-C resumes untouched."""
    snapshot = {
        "job_id": str(uuid4()),
        "job_type": "ingest",
        "url": "https://x.test/1",
        "cost_usd": 0.02,
    }
    restored = RunState.model_validate(snapshot)

    assert restored.stage_costs == []
    assert restored.cost_usd == 0.02
