"""P0-6: outcome classifier against fixture pages (DESIGN §10.7).

Synthetic pages in fixtures/pages/ pin each signal class; the corpus sweep at
the bottom runs over every real saved page as the corpus fills in (real pages
must classify success — they were saved because a human deemed them listings).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from manzil_shared.models import FetchOutcome
from manzil_worker.fetching.classifier import classify
from manzil_worker.fetching.cleaner import clean_html
from manzil_worker.fetching.corpus import corpus_pages
from manzil_worker.fetching.results import FetchResult

PAGES = Path(__file__).parent / "fixtures" / "pages"


def make_result(
    body: str,
    status: int = 200,
    headers: dict[str, str] | None = None,
    url: str = "https://example.com/listing",
    final_url: str | None = None,
    error: str | None = None,
) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=final_url or url,
        status_code=status,
        headers=headers or {},
        body=body,
        tier=1,
        error=error,
    )


def classify_page(fixture: str, **kwargs: object) -> FetchOutcome:
    body = (PAGES / fixture).read_text()
    result = make_result(body, **kwargs)  # type: ignore[arg-type]
    return classify(result, clean_html(body))


def test_cloudflare_challenge_is_blocked_even_with_200() -> None:
    assert classify_page("blocked_cloudflare.html") is FetchOutcome.BLOCKED


def test_px_interruption_page_is_blocked() -> None:
    assert classify_page("blocked_px.html", status=429) is FetchOutcome.BLOCKED


def test_403_status_is_blocked_regardless_of_body() -> None:
    assert classify_page("success_text.html", status=403) is FetchOutcome.BLOCKED


def test_challenge_cookie_is_blocked() -> None:
    outcome = classify_page("success_text.html", headers={"set-cookie": "cf_clearance=abc; path=/"})
    assert outcome is FetchOutcome.BLOCKED


def test_captcha_redirect_is_blocked() -> None:
    outcome = classify_page(
        "success_text.html",
        url="https://example.com/listing",
        final_url="https://example.com/px-captcha?src=listing",
    )
    assert outcome is FetchOutcome.BLOCKED


def test_js_shell_is_shell() -> None:
    assert classify_page("shell_js.html") is FetchOutcome.SHELL


def test_tiny_body_is_shell() -> None:
    assert (
        classify(
            make_result("<html><body>hi</body></html>"), clean_html("<html><body>hi</body></html>")
        )
        is FetchOutcome.SHELL
    )


def test_jsonld_short_circuits_to_success_despite_thin_text() -> None:
    assert classify_page("success_jsonld.html") is FetchOutcome.SUCCESS


def test_substantial_text_with_listing_signals_is_success() -> None:
    assert classify_page("success_text.html") is FetchOutcome.SUCCESS


def test_substantial_text_without_listing_signals_is_not_listing() -> None:
    assert classify_page("not_listing_article.html") is FetchOutcome.NOT_LISTING


def test_network_failure_is_error() -> None:
    result = make_result("", status=0, error="ConnectError('boom')")
    assert classify(result, clean_html("")) is FetchOutcome.ERROR


def test_plain_404_is_error_not_blocked() -> None:
    assert classify_page("not_listing_article.html", status=404) is FetchOutcome.ERROR


def test_missing_corpus_dir_is_empty_not_crash(tmp_path: Path) -> None:
    """Fresh clone: the corpus is a local eval asset (gitignored, §20 v2.8) —
    its absence must yield a clean skip, not a collection error."""
    assert corpus_pages(tmp_path / "never-created") == []


@pytest.mark.parametrize(
    "page_dir", corpus_pages() or [None], ids=lambda p: p.name if p else "corpus-empty"
)
def test_corpus_pages_classify_success(page_dir: Path | None) -> None:
    if page_dir is None:
        pytest.skip("corpus not collected yet (Phase 0, P0-11)")
    body = (page_dir / "raw.html").read_text(errors="replace")
    result = make_result(body, url=f"https://{page_dir.name.split('--')[0]}/x")
    assert classify(result, clean_html(body)) is FetchOutcome.SUCCESS
