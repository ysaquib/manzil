"""P3-3: the `fetch_page` tool is not an SSRF primitive — it runs VALIDATE_URL's
host checks first (identical to submission) and only then routes through the
tier ladder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from manzil_shared.config import FETCH_PAGE_EMBEDDED_MAX_CHARS, FETCH_PAGE_MAX_CHARS
from manzil_worker.fetching.registry import InMemoryRegistry
from manzil_worker.fetching.results import FetchResult
from manzil_worker.llm.tools import FetchPageBudget, ToolContext, fetch_page, tool_context

PAGES = Path(__file__).parent / "fixtures" / "pages"
SUCCESS_BODY = (PAGES / "success_text.html").read_text()


class FakeFetcher:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
        self.calls += 1
        return FetchResult(url=url, final_url=url, status_code=200, body=SUCCESS_BODY, tier=1)


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/admin",
        "https://127.0.0.1:8000/x",
        "https://192.168.1.1/router",
        "https://10.0.0.7/internal",
        "https://supabase.local/studio",
        "ftp://example.com/listing",
        "https://intranet/listings",
        "https://example.com/brochure.pdf",
    ],
)
async def test_fetch_page_refuses_ssrf_and_garbage_without_fetching(url: str) -> None:
    fetcher = FakeFetcher()
    ctx = ToolContext(fetchers={1: fetcher}, registry=InMemoryRegistry())
    with tool_context(ctx):
        result = await fetch_page(url)
    # A refusal is a dict, a fetched page is a str. The loop serialises both to
    # the same bytes for the model; the type is what lets the job-event summary
    # tell a reason from a page without parsing a page (see `_summarize`).
    assert isinstance(result, dict)
    assert "refused" in result["error"]
    assert fetcher.calls == 0  # the private/loopback target is never contacted


async def test_fetch_page_happy_path_returns_structured_page_brief() -> None:
    fetcher = FakeFetcher()
    ctx = ToolContext(fetchers={1: fetcher}, registry=InMemoryRegistry())
    with tool_context(ctx):
        page = await fetch_page("https://example.test/listing")
    assert fetcher.calls == 1
    assert page["outcome"] == "fetched"
    assert page["text"]  # cleaned, non-empty text came back
    assert page["structured_data"] == ""


async def test_fetch_page_caps_returned_length() -> None:
    class BigFetcher:
        async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
            body = "<html><body>" + ("word " * 100_000) + "</body></html>"
            return FetchResult(url=url, final_url=url, status_code=200, body=body, tier=1)

    ctx = ToolContext(fetchers={1: BigFetcher()}, registry=InMemoryRegistry())
    with tool_context(ctx):
        page = await fetch_page("https://example.test/huge")
    assert page["text_chars"] + page["structured_data_chars"] <= FETCH_PAGE_MAX_CHARS


async def test_the_job_event_records_the_fetch_and_not_the_page() -> None:
    """`job_events.detail` is member- and demo-readable, and `_summarize` used to
    store the first 2 KB of the cleaned body in it — the same class of data
    DESIGN §16 withholds everywhere else. Length and hash, never text."""
    from manzil_worker.llm.tools import _summarize, tool_spec

    fetcher = FakeFetcher()
    ctx = ToolContext(fetchers={1: fetcher}, registry=InMemoryRegistry())
    with tool_context(ctx):
        page = await fetch_page("https://example.test/listing")

    full, summary = _summarize(page, tool_spec(fetch_page))
    assert full == json.dumps(page)  # the model still sees the full structured brief
    recorded = json.loads(summary)
    assert recorded["outcome"] == "fetched"
    assert recorded["text_chars"] == page["text_chars"]
    assert recorded["structured_data_chars"] == page["structured_data_chars"]
    assert recorded["sha256"] == page["sha256"]
    for word in ("renovated", "countertops", "stainless", "Detroit"):
        assert word not in summary


async def test_fetch_page_reserves_space_for_embedded_data_at_the_end() -> None:
    state = json.dumps(
        {
            "listing": {
                "name": "Maple Court",
                "floorPlans": [{"name": "A1", "priceLow": 1450, "bedCount": 1}],
            }
        }
    )

    class EmbeddedFetcher:
        async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
            body = (
                "<html><body>"
                + ("ordinary listing prose " * 8_000)
                + f"</body><script>{'var pad=1;' * 50}window.__STATE__ = {state};</script></html>"
            )
            return FetchResult(url=url, final_url=url, status_code=200, body=body, tier=1)

    ctx = ToolContext(fetchers={1: EmbeddedFetcher()}, registry=InMemoryRegistry())
    with tool_context(ctx):
        page = await fetch_page("https://example.test/with-state")

    assert "Maple Court" in page["structured_data"]
    assert page["structured_data_chars"] <= FETCH_PAGE_EMBEDDED_MAX_CHARS
    assert page["text_chars"] + page["structured_data_chars"] <= FETCH_PAGE_MAX_CHARS


async def test_fetch_page_budget_stops_extra_calls_before_fetching() -> None:
    fetcher = FakeFetcher()
    budget = FetchPageBudget(max_calls=1, max_tier3_fetches=1, max_chars=FETCH_PAGE_MAX_CHARS)
    ctx = ToolContext(fetchers={1: fetcher}, registry=InMemoryRegistry(), fetch_page_budget=budget)
    with tool_context(ctx):
        first = await fetch_page("https://example.test/one")
        second = await fetch_page("https://example.test/two")

    assert first["outcome"] == "fetched"
    assert second == {"error": "budget_exhausted", "reason": "fetch_page call budget exhausted"}
    assert fetcher.calls == 1


async def test_fetch_page_budget_allows_only_one_tier3_escalation() -> None:
    class BlockedTierOne:
        tier = 1

        def __init__(self) -> None:
            self.calls = 0

        async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
            self.calls += 1
            return FetchResult(
                url=url, final_url=url, status_code=403, body="blocked", tier=self.tier
            )

    class WorkingTierThree:
        tier = 3

        def __init__(self) -> None:
            self.calls = 0

        async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
            self.calls += 1
            return FetchResult(
                url=url,
                final_url=url,
                status_code=200,
                body=SUCCESS_BODY,
                tier=self.tier,
            )

    tier_one, tier_three = BlockedTierOne(), WorkingTierThree()
    budget = FetchPageBudget(max_calls=2, max_tier3_fetches=1, max_chars=FETCH_PAGE_MAX_CHARS * 2)
    ctx = ToolContext(
        fetchers={1: tier_one, 3: tier_three},
        registry=InMemoryRegistry(),
        fetch_page_budget=budget,
    )
    with tool_context(ctx):
        await fetch_page("https://example.test/one")
        await fetch_page("https://example.test/two")

    assert budget.tier3_fetches_used == 1
    assert tier_three.calls == 1
    assert tier_one.calls == 2


async def test_a_refusal_reaches_the_model_and_the_event_unchanged() -> None:
    """Narrowing the summary must not cost the operator the reason a fetch was
    refused — the SSRF refusals are the most useful thing in that log."""
    from manzil_worker.llm.tools import _summarize, tool_spec

    ctx = ToolContext(fetchers={1: FakeFetcher()}, registry=InMemoryRegistry())
    with tool_context(ctx):
        refusal = await fetch_page("https://127.0.0.1:8000/x")

    full, summary = _summarize(refusal, tool_spec(fetch_page))
    # Byte-identical to what the pre-change tool handed the model.
    assert full == json.dumps({"error": refusal["error"]})
    assert "refused" in json.loads(summary)["error"]
