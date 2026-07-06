"""Fixture-corpus tooling (P0-5, IMPLEMENTATION §5).

Corpus layout — one directory per saved listing page:
    worker/tests/fixtures/corpus/{domain}--{slug}/
        raw.html      # as saved from the browser
        cleaned.txt   # produced by the cleaner (regenerate when cleaner changes)
        meta.json     # url, saved_at, is_official, notes
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from manzil_worker.fetching.cleaner import clean_html
from manzil_worker.fetching.results import FetchResult
from manzil_worker.fetching.tiers import site_domain

CORPUS_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "corpus"


def corpus_pages(corpus_dir: Path = CORPUS_DIR) -> list[Path]:
    return sorted(p for p in corpus_dir.iterdir() if (p / "raw.html").exists())


def regenerate_cleaned(corpus_dir: Path = CORPUS_DIR) -> list[tuple[str, int, int]]:
    """Re-run the cleaner over every corpus page (runbook: regenerate when the
    cleaner changes). Returns (slug, raw_bytes, cleaned_chars) per page."""
    report: list[tuple[str, int, int]] = []
    for page_dir in corpus_pages(corpus_dir):
        raw = (page_dir / "raw.html").read_text(errors="replace")
        cleaned = clean_html(raw)
        (page_dir / "cleaned.txt").write_text(cleaned.text)
        report.append((page_dir.name, len(raw), len(cleaned.text)))
    return report


def save_page(
    result: FetchResult,
    slug: str,
    *,
    is_official: bool,
    notes: str = "",
    corpus_dir: Path = CORPUS_DIR,
) -> Path:
    """Persist a fetched page as a new corpus fixture directory."""
    page_dir = corpus_dir / f"{site_domain(result.url)}--{slug}"
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "raw.html").write_text(result.body)
    (page_dir / "cleaned.txt").write_text(clean_html(result.body).text)
    (page_dir / "meta.json").write_text(
        json.dumps(
            {
                "url": result.url,
                "saved_at": datetime.now(UTC).isoformat(),
                "is_official": is_official,
                "notes": notes,
                "tier": result.tier,
                "status_code": result.status_code,
            },
            indent=2,
        )
        + "\n"
    )
    return page_dir
