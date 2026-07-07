"""Per-stage model map (DESIGN §11.1-11.2, IMPLEMENTATION §3).

Pinned model IDs, per-stage assignment, and list prices for the cost tally.
Swapping a stage's model is a config change here — nowhere else. P0-13 (model
bench) settles these choices empirically and rewrites this file; until then
the all-Anthropic baseline from §11.2 stands.

Provider is derived from the model ID (`claude-*` → Anthropic, `gemini-*` →
Google); the adapters live in `llm/client.py`. Adding a model to the bench =
one MODEL_PRICES entry here. Adopting a non-Anthropic model as a *default*
pin additionally requires bench evidence + a DESIGN §20 entry (P0-14).
"""

from __future__ import annotations

import os

# Baseline pins (§11.2). Dated IDs where published; verify at P0-13 before
# committing bench results — a silent model change must never wobble scores.
WORKHORSE_MODEL = "claude-haiku-4-5-20251001"
TASTE_MODEL = "claude-sonnet-4-6"

# Stage -> model. Unknown stage is an error, not a fallback: a new stage must
# be assigned a tier deliberately (and get a prompt file) before it can call.
STAGE_MODELS: dict[str, str] = {
    # workhorse tier
    "smoke": WORKHORSE_MODEL,  # P0-7 seam check; cheapest tier on purpose
    "validate": WORKHORSE_MODEL,
    "extract": WORKHORSE_MODEL,
    "verify": WORKHORSE_MODEL,  # check 4 only; checks 1-3 are code
    "reconcile_equivalence": WORKHORSE_MODEL,
    "custom_match": WORKHORSE_MODEL,
    "plan_assist": WORKHORSE_MODEL,
    # taste tier
    "vision": TASTE_MODEL,
    "discover": TASTE_MODEL,
}

DEFAULT_MAX_TOKENS = 2048
STAGE_MAX_TOKENS: dict[str, int] = {
    "smoke": 256,
    "extract": 8192,  # full catalog-wide extraction is the largest output
}

# List $ / MTok (input, output) — §11.2 table, mid-2026. The Gemini rows are
# the P0-13 bench candidates; pricing a model here is what makes it callable
# (cost accounting never guesses). Used for the RunState cost tally; the
# Langfuse-side cost comes from these same figures so there is one source.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    WORKHORSE_MODEL: (1.00, 5.00),
    TASTE_MODEL: (3.00, 15.00),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
}

# Cache economics differ per provider: Anthropic bills explicit cache reads at
# 10% and writes at 125%; Gemini's implicit caching bills cached reads at 25%
# with no write premium.
CACHE_READ_MULTIPLIERS: dict[str, float] = {"anthropic": 0.10, "google": 0.25}
CACHE_WRITE_MULTIPLIERS: dict[str, float] = {"anthropic": 1.25, "google": 0.0}


def provider_for_model(model: str) -> str:
    """Derive the provider from the model ID — the seam's dispatch key."""
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith("gemini-"):
        return "google"
    raise KeyError(
        f"model {model!r}: unknown provider prefix — the seam only speaks "
        "anthropic (claude-*) and google (gemini-*)"
    )


def model_for_stage(stage: str) -> str:
    """Pinned model for a stage. `MANZIL_MODEL_<STAGE>` overrides the pin for
    bench/dev runs (P0-13 sweeps models without editing pins); the override
    must be priced in MODEL_PRICES so cost accounting never guesses."""
    override = os.environ.get(f"MANZIL_MODEL_{stage.upper()}")
    if override:
        if override not in MODEL_PRICES:
            raise KeyError(
                f"MANZIL_MODEL_{stage.upper()}={override!r} is not in MODEL_PRICES — "
                "add its list price to llm/config.py before calling it"
            )
        return override
    try:
        return STAGE_MODELS[stage]
    except KeyError:
        raise KeyError(
            f"stage {stage!r} has no model assignment in llm/config.py — "
            "assign it a tier deliberately before it can call"
        ) from None


def max_tokens_for_stage(stage: str) -> int:
    return STAGE_MAX_TOKENS.get(stage, DEFAULT_MAX_TOKENS)


def cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """List-price cost of one call. `input_tokens` is uncached input only —
    each adapter normalizes its provider's usage fields to that convention."""
    in_price, out_price = MODEL_PRICES[model]
    provider = provider_for_model(model)
    return (
        input_tokens * in_price
        + cache_read_tokens * in_price * CACHE_READ_MULTIPLIERS[provider]
        + cache_write_tokens * in_price * CACHE_WRITE_MULTIPLIERS[provider]
        + output_tokens * out_price
    ) / 1_000_000
