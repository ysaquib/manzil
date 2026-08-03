"""P0-7: LLM client seam — prompt loading, record/replay, cost tally, NFR6 guard.

No live LLM calls here, ever (AGENTS.md): the replay tests read committed
fixtures; the record test stubs the provider call. The one genuinely live
call is the user-run `manzil llm-smoke`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from manzil_worker.llm import client as client_mod
from manzil_worker.llm.client import (
    ProviderResponse,
    SeamConfigError,
    VisionImage,
    call_structured,
    call_vision,
    cost_tally,
)
from manzil_worker.llm.config import (
    WORKHORSE_MODEL,
    cost_usd,
    model_for_stage,
    openrouter_provider_order,
    provider_for_model,
)
from manzil_worker.llm.prompt_loader import Prompt, PromptError, load_prompt
from manzil_worker.llm.recording import ReplayMissError, request_hash
from manzil_worker.llm.smoke import SMOKE_TOKEN, SmokeResult, run_smoke

# ── prompt loader ────────────────────────────────────────────────────────────


def test_smoke_prompt_loads_and_splits_at_marker() -> None:
    prompt = load_prompt("smoke")
    assert prompt.id == "smoke"
    assert prompt.version == 1
    assert "smoke check" in prompt.cacheable_prefix
    assert prompt.per_call == "Read the token from the user message and emit the structured result."
    assert "<!-- PER-CALL -->" not in prompt.cacheable_prefix
    assert "<!-- PER-CALL -->" not in prompt.per_call


def test_reconcile_equivalence_prompt_uses_batched_item_contract() -> None:
    prompt = load_prompt("reconcile_equivalence")
    assert prompt.id == "reconcile_equivalence"
    assert prompt.version == 2
    assert "item_id exactly once" in prompt.per_call
    assert "within the same target_key" in " ".join(prompt.per_call.split())


def test_prompt_without_marker_is_all_per_call(tmp_path: Path) -> None:
    (tmp_path / "validate.md").write_text("---\nid: validate\nversion: 3\n---\nJudge the page.\n")
    prompt = load_prompt("validate", prompts_dir=tmp_path)
    assert prompt.cacheable_prefix == ""
    assert prompt.per_call == "Judge the page."
    assert prompt.version == 3


@pytest.mark.parametrize(
    "text",
    [
        "no front matter at all",
        "---\nid: x\n---\nbody",  # missing version
        "---\nid: x\nversion: 1\nnever terminated",
        "---\nid: x\nversion: 1\ncacheable_prefix_marker: <!-- M -->\n---\nmarker absent",
    ],
)
def test_malformed_prompts_fail_loudly(tmp_path: Path, text: str) -> None:
    (tmp_path / "bad.md").write_text(text)
    with pytest.raises(PromptError):
        load_prompt("bad", prompts_dir=tmp_path)


def test_missing_prompt_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="no prompt file"):
        load_prompt("ghost", prompts_dir=tmp_path)


# ── request hash (IMPL §5: stage, model_id, prompt_version, sha256(content)) ─


def test_request_hash_covers_exactly_the_four_components() -> None:
    base = request_hash("extract", "model-a", 1, "content")
    assert base == request_hash("extract", "model-a", 1, "content")  # stable
    assert base != request_hash("verify", "model-a", 1, "content")
    assert base != request_hash("extract", "model-b", 1, "content")
    assert base != request_hash("extract", "model-a", 2, "content")
    assert base != request_hash("extract", "model-a", 1, "other content")


# ── replay ───────────────────────────────────────────────────────────────────


def test_replay_serves_the_committed_smoke_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The P0-7 'replay test green' gate: the exact call `manzil llm-smoke`
    makes is served from the committed fixture — zero tokens, no keys."""
    monkeypatch.setenv("MANZIL_LLM_MODE", "replay")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with cost_tally() as tally:
        result = asyncio.run(run_smoke())

    assert result.echo == SMOKE_TOKEN
    assert tally.calls == 1
    assert tally.cost_usd > 0  # replay still tallies the recorded usage


def test_replay_miss_fails_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANZIL_LLM_MODE", "replay")
    with pytest.raises(ReplayMissError, match="replay miss"):
        asyncio.run(call_structured("smoke", SmokeResult, "Token: never-recorded"))


# ── record -> replay round trip (provider stubbed; no tokens spent) ──────────


def test_record_then_replay_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MANZIL_RECORDED_DIR", str(tmp_path))

    stub = ProviderResponse(
        output={"echo": "round-trip", "model_family": "stub"},
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=50,
        cache_write_tokens=10,
    )

    async def fake_traced_live_call(plan: object, schema: object) -> ProviderResponse:
        return stub

    monkeypatch.setattr(client_mod, "_traced_live_call", fake_traced_live_call)
    monkeypatch.setenv("MANZIL_LLM_MODE", "record")
    recorded = asyncio.run(call_structured("smoke", SmokeResult, "Token: round-trip"))
    assert recorded == SmokeResult(echo="round-trip", model_family="stub")

    fixtures = list(tmp_path.glob("smoke--*.json"))
    assert len(fixtures) == 1
    data = json.loads(fixtures[0].read_text())
    assert data["model"] == model_for_stage("smoke")
    assert data["prompt_version"] == 1
    assert data["input_tokens"] == 100

    # Same request in replay mode is served from the file just written,
    # without the (stubbed) provider: remove the stub to prove it.
    monkeypatch.setattr(client_mod, "_traced_live_call", None)
    monkeypatch.setenv("MANZIL_LLM_MODE", "replay")
    with cost_tally() as tally:
        replayed = asyncio.run(call_structured("smoke", SmokeResult, "Token: round-trip"))
    assert replayed == recorded
    assert tally.input_tokens == 100
    assert tally.cache_read_tokens == 50
    assert tally.cost_usd == pytest.approx(
        cost_usd(
            WORKHORSE_MODEL,
            input_tokens=100,
            output_tokens=20,
            cache_read_tokens=50,
            cache_write_tokens=10,
        )
    )


def test_vision_recording_hashes_images_without_storing_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MANZIL_RECORDED_DIR", str(tmp_path))
    monkeypatch.setenv("MANZIL_LLM_MODE", "record")
    monkeypatch.setattr(
        client_mod,
        "load_prompt",
        lambda stage: Prompt(id="vision", version=1, cacheable_prefix="anchored", per_call="rate"),
    )
    response = ProviderResponse(
        output={"echo": "rated", "model_family": "stub"},
        input_tokens=25,
        output_tokens=5,
    )

    async def fake_call(plan, schema, images):  # type: ignore[no-untyped-def]
        assert images[0].data == b"webp bytes"
        return response

    monkeypatch.setattr(client_mod, "_traced_live_vision_call", fake_call)
    data = b"webp bytes"
    image = VisionImage(content_hash=hashlib.sha256(data).hexdigest(), data=data)
    result = asyncio.run(call_vision("vision", SmokeResult, [image]))
    assert result.echo == "rated"

    fixture = next(tmp_path.glob("vision--*.json"))
    text = fixture.read_text()
    assert image.content_hash in text
    assert "webp bytes" not in text
    monkeypatch.setenv("MANZIL_LLM_MODE", "replay")
    monkeypatch.setattr(client_mod, "_traced_live_vision_call", None)
    assert asyncio.run(call_vision("vision", SmokeResult, [image])) == result


# ── NFR6 guard: an untraced live call is a bug, not a degraded mode ──────────


def test_live_call_without_langfuse_keys_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MANZIL_LLM_MODE", "live")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-never-used")
    with pytest.raises(SeamConfigError, match="NFR6"):
        asyncio.run(call_structured("smoke", SmokeResult, "Token: anything"))


def test_unknown_stage_has_no_silent_fallback() -> None:
    with pytest.raises(KeyError, match="no model assignment"):
        model_for_stage("brand-new-stage")


def test_image_classify_uses_owner_selected_taste_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MANZIL_MODEL_IMAGE_CLASSIFY", raising=False)
    assert model_for_stage("image_classify") == "anthropic/claude-sonnet-4.6"


# ── OpenRouter routing + cache economics ─────────────────────────────────────


def test_provider_derives_cache_family_from_openrouter_slug() -> None:
    assert provider_for_model("anthropic/claude-haiku-4.5") == "anthropic"
    assert provider_for_model("google/gemini-2.5-flash-lite") == "google"
    # openai/qwen/deepseek/mistral/minimax gained cache multipliers 2026-07-18;
    # an actually-unpriced family still refuses.
    with pytest.raises(KeyError, match="unknown vendor family"):
        provider_for_model("zai/glm-5")


def test_openrouter_provider_order_pins_upstream_vendors() -> None:
    assert openrouter_provider_order("anthropic/claude-haiku-4.5") == ["Anthropic"]
    assert openrouter_provider_order("google/gemini-2.5-flash-lite") == ["Google AI Studio"]


def test_model_override_env_swaps_the_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """P0-13 bench runs sweep models via MANZIL_MODEL_<STAGE> without editing
    pins; an unpriced override is refused so cost accounting never guesses."""
    monkeypatch.setenv("MANZIL_MODEL_SMOKE", "google/gemini-2.5-flash-lite")
    assert model_for_stage("smoke") == "google/gemini-2.5-flash-lite"
    monkeypatch.setenv("MANZIL_MODEL_SMOKE", "google/gemini-9.9-imaginary")
    with pytest.raises(KeyError, match="not in MODEL_PRICES"):
        model_for_stage("smoke")


def test_gemini_pricing_uses_google_cache_economics() -> None:
    # 1M uncached in + 1M out at (0.10, 0.40); cache reads at 25%, no write premium.
    assert cost_usd(
        "google/gemini-2.5-flash-lite", input_tokens=1_000_000, output_tokens=1_000_000
    ) == pytest.approx(0.50)
    assert cost_usd(
        "google/gemini-2.5-flash-lite", input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000
    ) == pytest.approx(0.025)


def test_live_call_routes_all_models_through_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    stub = ProviderResponse(
        output={"echo": "x", "model_family": "stub"}, input_tokens=1, output_tokens=1
    )

    async def fake_openrouter(plan: object, schema: object) -> ProviderResponse:
        calls.append("openrouter")
        return stub

    monkeypatch.setattr(client_mod, "_live_call_openrouter", fake_openrouter)

    for model in ("google/gemini-2.5-flash-lite", WORKHORSE_MODEL):
        plan = client_mod._CallPlan(
            stage="smoke",
            model=model,
            prompt=load_prompt("smoke"),
            content="Token: x",
            digest="d",
        )
        asyncio.run(client_mod._live_call(plan, SmokeResult))
    assert calls == ["openrouter", "openrouter"]


def test_tool_schema_inlines_nested_pydantic_refs() -> None:
    """Gemini's OpenRouter function adapter flattened $ref objects to strings;
    the provider-facing schema must carry the full nested shape inline."""
    from pydantic import BaseModel

    class Nested(BaseModel):
        value: int | None

    class Outer(BaseModel):
        nested: Nested
        many: list[Nested]

    schema = client_mod._tool_schema(Outer)
    serialized = json.dumps(schema)

    assert "$ref" not in serialized
    assert "$defs" not in serialized
    assert schema["properties"]["nested"]["properties"]["value"]["anyOf"]
    assert schema["properties"]["many"]["items"]["properties"]["value"]["anyOf"]


def test_tool_schema_removes_keywords_google_rejects() -> None:
    """The dynamic EXTRACT schema uses both constraints at multiple depths."""
    from manzil_worker.stages.schema_gen import build_extraction_schema

    schema = client_mod._tool_schema(build_extraction_schema())
    serialized = json.dumps(schema)

    assert '"uniqueItems"' not in serialized
    assert '"additionalProperties"' not in serialized


def test_bad_llm_mode_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANZIL_LLM_MODE", "yolo")
    with pytest.raises(SeamConfigError, match="expected live"):
        client_mod.llm_mode()
