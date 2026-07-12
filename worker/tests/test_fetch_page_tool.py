"""P3-3: the `fetch_page` tool is not an SSRF primitive — it runs VALIDATE_URL's
host checks first (identical to submission) and only then routes through the
tier ladder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from manzil_worker.fetching.registry import InMemoryRegistry
from manzil_worker.fetching.results import FetchResult
from manzil_worker.llm.tools import ToolContext, fetch_page, tool_context

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
    payload = json.loads(result)
    assert "refused" in payload["error"]
    assert fetcher.calls == 0  # the private/loopback target is never contacted


async def test_fetch_page_happy_path_returns_cleaned_text() -> None:
    fetcher = FakeFetcher()
    ctx = ToolContext(fetchers={1: fetcher}, registry=InMemoryRegistry())
    with tool_context(ctx):
        text = await fetch_page("https://example.test/listing")
    assert fetcher.calls == 1
    assert isinstance(text, str)
    assert text  # cleaned, non-empty text came back


async def test_fetch_page_caps_returned_length() -> None:
    from manzil_shared.config import FETCH_PAGE_MAX_CHARS

    class BigFetcher:
        async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
            body = "<html><body>" + ("word " * 100_000) + "</body></html>"
            return FetchResult(url=url, final_url=url, status_code=200, body=body, tier=1)

    ctx = ToolContext(fetchers={1: BigFetcher()}, registry=InMemoryRegistry())
    with tool_context(ctx):
        text = await fetch_page("https://example.test/huge")
    assert len(text) <= FETCH_PAGE_MAX_CHARS
