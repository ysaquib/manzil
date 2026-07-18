"""Per-stage model map (DESIGN §11.1-11.2, IMPLEMENTATION §3).

Pinned OpenRouter model slugs, per-stage assignment, and list prices for the
cost tally. Swapping a stage's model is a config change here — nowhere else.
P0-13 (model bench) settles these choices empirically and rewrites this file;
until then the all-Anthropic baseline from §11.2 stands (routed via OpenRouter).

Cache economics are keyed by upstream family (`anthropic/` → Anthropic rates,
`google/` → Google rates). Provider pinning for deterministic routing lives in
`openrouter_provider_order`. Adopting a non-Anthropic model as a *default* pin
additionally requires bench evidence + a DESIGN §20 entry (P0-14).
"""

from __future__ import annotations

import os

# Baseline pins (§11.2) as OpenRouter slugs. Verify at P0-13 before committing
# bench results — a silent model change must never wobble scores.
WORKHORSE_MODEL = "anthropic/claude-haiku-4.5"
TASTE_MODEL = "anthropic/claude-sonnet-4.6"

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

# Per-stage tool allow-lists (DESIGN §10.2, §16). The zero-tool property of
# extraction stages is a SECURITY CONTROL, not an omission: worst-case prompt
# injection from a scraped page stays "one bad value", never an action. Exactly
# two stages may run a bounded tool loop in workflow mode (AGENTS.md hard rule),
# so this table has exactly two non-empty rows — it IS that rule's enforcement.
# Every other stage (extract, verify, validate, …) resolves to an empty tuple,
# and `call_agent` refuses any stage absent from this map.
#   discover              — P3-5 DISCOVER. `web_search` (provider-hosted) is added
#                           when P3-5 lands; `fetch_page` is available now.
#   custom_match_location — P3-10 location-type custom-criteria dispatch (the
#                           second, and last, allowed loop).
STAGE_TOOLS: dict[str, tuple[str, ...]] = {
    "discover": ("fetch_page",),
    "custom_match_location": ("geocode", "places_nearby", "commute_time", "fetch_page"),
}


def allowed_tools(stage: str) -> tuple[str, ...]:
    """The tool names `stage` may use. Empty for every stage not explicitly
    allow-listed — extraction stages included. `call_agent` enforces this."""
    return STAGE_TOOLS.get(stage, ())


DEFAULT_MAX_TOKENS = 2048
STAGE_MAX_TOKENS: dict[str, int] = {
    "smoke": 256,
    "extract": 8192,  # full catalog-wide extraction is the largest output
}

# List $ / MTok (input, output) — §11.2 table, mid-2026. The Gemini rows are
# the P0-13 bench candidates; pricing a model here is what makes it callable
# (cost accounting never guesses). Used for the RunState cost tally; the
# Langfuse-side cost comes from these same figures so there is one source.
# OpenRouter's reported `usage.cost` is logged as a cross-check in traces.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    WORKHORSE_MODEL: (1.00, 5.00),
    TASTE_MODEL: (3.00, 15.00),
    "deepseek/deepseek-v4-flash": (0.09, 0.18),
    "google/gemini-2.5-flash-lite": (0.10, 0.40),
    "openai/gpt-5.4-nano": (0.20, 1.25),
    "anthropic/claude-3-haiku": (0.25, 1.25),
    "qwen/qwen3.5-flash": (0.25, 1.50),
    "google/gemini-3.1-flash-lite": (0.25, 1.50),
    "google/gemini-2.5-flash": (0.30, 2.50),
    "google/gemini-3-flash-preview": (0.50, 3.00),
    "openai/gpt-5.6-luna": (1.00, 6.00),
    "google/gemini-3.5-flash": (1.50, 9.00),
    "google/gemini-3.1-pro-preview": (2.00, 12.00),
}

# Cache economics differ per upstream family: Anthropic bills explicit cache
# reads at 10% and writes at 125%; Gemini's implicit caching bills cached reads
# at 25% with no write premium.
CACHE_READ_MULTIPLIERS: dict[str, float] = {"anthropic": 0.10, "google": 0.25}
CACHE_WRITE_MULTIPLIERS: dict[str, float] = {"anthropic": 1.25, "google": 0.0}

# OpenRouter provider slugs for deterministic routing (§11.3 model pinning).
_OPENROUTER_PROVIDER_ORDERS: dict[str, list[str]] = {
    "anthropic": ["Anthropic"],
    "google": ["Google AI Studio"],
}


def _model_family(model: str) -> str:
    """Upstream family from an OpenRouter slug (`vendor/model`)."""
    if "/" not in model:
        raise KeyError(
            f"model {model!r}: expected OpenRouter slug form vendor/model — "
            "the seam routes all calls through OpenRouter"
        )
    return model.split("/", 1)[0]


def provider_for_model(model: str) -> str:
    """Cache-economics family for a model slug — used by cost_usd."""
    family = _model_family(model)
    if family not in CACHE_READ_MULTIPLIERS:
        raise KeyError(
            f"model {model!r}: unknown vendor family {family!r} — add cache "
            "multipliers to llm/config.py before calling it"
        )
    return family


def openrouter_provider_order(model: str) -> list[str]:
    """Pinned upstream provider order for OpenRouter routing."""
    family = _model_family(model)
    try:
        return _OPENROUTER_PROVIDER_ORDERS[family]
    except KeyError:
        raise KeyError(
            f"model {model!r}: no OpenRouter provider order for family "
            f"{family!r} — add an entry to _OPENROUTER_PROVIDER_ORDERS"
        ) from None


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
    the OpenRouter adapter normalizes usage fields to that convention."""
    in_price, out_price = MODEL_PRICES[model]
    provider = provider_for_model(model)
    return (
        input_tokens * in_price
        + cache_read_tokens * in_price * CACHE_READ_MULTIPLIERS[provider]
        + cache_write_tokens * in_price * CACHE_WRITE_MULTIPLIERS[provider]
        + output_tokens * out_price
    ) / 1_000_000
