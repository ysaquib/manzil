"""Per-stage model map (DESIGN §11.1-11.2, IMPLEMENTATION §3).

Pinned model IDs, per-stage assignment, and list prices for the cost tally.
Swapping a stage's model is a config change here — nowhere else. P0-13 (model
bench) settles these choices empirically and rewrites this file; until then
the all-Anthropic baseline from §11.2 stands.
"""

from __future__ import annotations

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

# List $ / MTok (input, output) — §11.2 table, mid-2026. Cache reads bill at
# 10% of input; cache writes at 125%. Used for the RunState cost tally; the
# Langfuse-side cost comes from these same figures so there is one source.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    WORKHORSE_MODEL: (1.00, 5.00),
    TASTE_MODEL: (3.00, 15.00),
}
CACHE_READ_MULTIPLIER = 0.10
CACHE_WRITE_MULTIPLIER = 1.25


def model_for_stage(stage: str) -> str:
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
    """List-price cost of one call. Uncached input excludes cache reads/writes
    (Anthropic reports them in separate usage fields)."""
    in_price, out_price = MODEL_PRICES[model]
    return (
        input_tokens * in_price
        + cache_read_tokens * in_price * CACHE_READ_MULTIPLIER
        + cache_write_tokens * in_price * CACHE_WRITE_MULTIPLIER
        + output_tokens * out_price
    ) / 1_000_000
