"""Label-free corpus EXTRACT -> VERIFY diagnostic runner."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest
from manzil_worker.evals.corpus_run import run_corpus_extraction
from manzil_worker.fetching.cleaner import clean_html
from manzil_worker.phase0_rubric import phase0_rubric
from manzil_worker.stages.base import StageCtx
from worker_helpers import PAGES, FakeLLM, maple_extraction

SLUG = "example.test--maple"
URL = "https://example.test/listing"


def _corpus(tmp_path: Path, *, saved_at: str = "2026-07-02T18:00:00+00:00") -> Path:
    corpus = tmp_path / "corpus"
    page = corpus / SLUG
    page.mkdir(parents=True)
    cleaned = clean_html((PAGES / "e2e_listing.html").read_text()).text
    (page / "cleaned.txt").write_text(cleaned)
    (page / "meta.json").write_text(
        json.dumps(
            {
                "url": URL,
                "saved_at": saved_at,
                "tier": 2,
                "is_official": True,
            }
        )
    )
    return corpus


def test_runs_extract_then_verify_without_a_label(tmp_path: Path) -> None:
    fake = FakeLLM({"extract": maple_extraction(), "verify": {"contradictions": []}})
    result = asyncio.run(
        run_corpus_extraction(
            SLUG,
            corpus_dir=_corpus(tmp_path),
            ctx=StageCtx(call_structured=fake, rubric=phase0_rubric()),
        )
    )

    assert [stage for stage, _ in fake.calls] == ["extract", "verify"]
    assert result.slug == SLUG
    assert result.url == URL
    assert result.as_of_date == date(2026, 7, 2)
    assert next(c for c in result.source_claims if c.criterion_key == "beds").value == 2
    assert result.floor_plans[0].plan_name == "The Maple"
    assert result.property_identity is not None
    assert result.property_identity.name == "Maple Court Apartments"
    assert result.verify_flags == []
    assert result.checkpoint is None


def test_surfaces_verify_checkpoint_without_losing_audit_result(tmp_path: Path) -> None:
    payload = maple_extraction()
    payload["beds"] = {
        "value": 2,
        "confidence": "medium",
        "evidence_quote": "this quote is absent from the page",
    }
    fake = FakeLLM({"extract": payload, "verify": {"contradictions": []}})

    result = asyncio.run(
        run_corpus_extraction(
            SLUG,
            corpus_dir=_corpus(tmp_path),
            ctx=StageCtx(call_structured=fake, rubric=phase0_rubric()),
        )
    )

    assert next(c for c in result.source_claims if c.criterion_key == "beds").value == 2
    assert any(flag.criterion_key == "beds" for flag in result.verify_flags)
    assert result.checkpoint is not None
    assert result.checkpoint.context_ref == "beds"


def test_missing_page_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="save-page"):
        asyncio.run(
            run_corpus_extraction(
                "example.test--missing",
                corpus_dir=tmp_path,
                ctx=StageCtx(),
            )
        )
