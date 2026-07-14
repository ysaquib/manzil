"""Tunables — single home, no magic numbers in stage code (IMPLEMENTATION.md §3).

The single-home rule is settled; every value is a starting point expected to
be tuned against Phase 0 reality (tune freely, changelog-note the change).
"""

# VERIFY check 1 — evidence audit (rapidfuzz partial_ratio)
EVIDENCE_FUZZY_THRESHOLD = 85

# RECONCILE rung 2 — numeric tolerance collapse (percent)
RENT_AGREE_PCT = 3.0
SQFT_AGREE_PCT = 5.0

# VERIFY check 3 — plausibility bands cold start (listings per metro)
PLAUSIBILITY_COLD_START_N = 8

# VERIFY check 3 — static sanity bounds used until a metro's self-derived
# bands exist (Phase 0 is always cold start; DESIGN §10.5)
RENT_PLAUSIBLE_MIN = 400.0
RENT_PLAUSIBLE_MAX = 10_000.0
SQFT_PER_BED_MIN = 250
SQFT_PER_BED_MAX = 2_500
DEPOSIT_MAX_RENT_MULTIPLIER = 2.0

# Runner retry policy: STAGE_RETRIES attempts, 10s * 2^attempt jittered
STAGE_RETRIES = 3
STAGE_BACKOFF_BASE_SECONDS = 10

# Queue reclaim: a running job without a heartbeat this long is orphaned
JOB_ORPHAN_AFTER_SECONDS = 5 * 60

# Queue dead-letter cap: an orphaned job reclaimed this many times is dead-lettered
# to `failed` instead of re-queued (a crash loop must not churn the queue forever).
# A manual retry resets `attempts`, granting a fresh cycle budget.
MANZIL_JOB_MAX_ATTEMPTS = 5

# Worker loop: how long to sleep between claim attempts when the queue is empty
# (the loop wakes early on a clean-shutdown signal, so this only bounds idle poll rate)
WORKER_IDLE_BACKOFF_SECONDS = 1.0

# P3 bounded tool loops
AGENT_MAX_TURNS = 8
# Tool-call observability (§10.2): a tool result can be a whole page, so the
# `tool_called` job event stores only a truncated summary — the full result still
# goes back to the model in the loop.
AGENT_TOOL_RESULT_SUMMARY_CAP = 2048
# `fetch_page` tool: cleaned text handed back to an agent is capped so one fetch
# cannot blow the turn's context budget (the full page still persists via FETCH).
FETCH_PAGE_MAX_CHARS = 20_000
# Maps HTTP wrappers (enrich/maps.py): retry count + base backoff for quota
# (HTTP 429 / Google OVER_QUERY_LIMIT) — small; Maps is inside the free credit.
MAPS_MAX_RETRIES = 3
MAPS_BACKOFF_BASE_SECONDS = 0.5
MAPS_TIMEOUT_SECONDS = 15.0

# Planner (P3-2, DESIGN §10.4/§14): a persisted source whose `cleaned_text_hash`
# is set and whose `last_success_at` is within this window is planned
# `action: skip, why: hash_fresh` — FETCH loads the stored cleaned text instead
# of re-fetching. 24h is §14's conservative PRICING bound (the fastest-moving
# refresh class), so no source is ever skipped past the tightest TTL.
PLAN_FRESH_TTL_HOURS = 24

# Planner cost estimate (P3-2, DESIGN §10.4/§2.7): flat per-stage USD estimates
# summed over the manifest's non-skipped stages to fill `est_cost_usd`. Rough by
# design — the column exists so the planned estimate and the actual bill
# (`cost_actual_usd`) can be compared, not to be a forecast. The LLM-bearing
# stages (VALIDATE/EXTRACT/VERIFY) carry the cost; the deterministic ones are 0.
STAGE_COST_ESTIMATES_USD = {
    "PLAN": 0.0,
    "VALIDATE_URL": 0.0,
    "FETCH": 0.0,
    "VALIDATE": 0.005,
    "EXTRACT": 0.02,
    "DEDUPE": 0.0,  # geocode is a Maps call, not an LLM call; no LLM cost here
    "IMAGE_FETCH": 0.0,
    "VISION": 0.03,
    "VERIFY": 0.01,
    "SCORE": 0.0,
}

# DEDUPE (P3-4, DESIGN §10.3): a candidate property is a merge target only when
# it is within DEDUPE_MAX_DISTANCE_METERS of the geocoded address. Above the AUTO
# name-similarity (rapidfuzz token_sort_ratio, 0-100) the merge is automatic;
# between GRAY and AUTO it is genuine ambiguity → a `resolve_dedupe` checkpoint;
# below GRAY the properties stay separate. Conservative by design (R5): a false
# split is recoverable by re-merge, a false merge poisons shared facts.
DEDUPE_MAX_DISTANCE_METERS = 100.0
DEDUPE_NAME_AUTO_SIMILARITY = 90.0
DEDUPE_NAME_GRAY_SIMILARITY = 60.0

# Scheduler sweep: unanswered checkpoints auto-resume after this long
CHECKPOINT_TIMEOUT_HOURS = 24

# VISION input discipline
MAX_IMAGES = 8
IMAGE_MAX_DIM = 1024
IMAGE_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
IMAGE_MAX_PIXELS = 40_000_000
IMAGE_WEBP_QUALITY = 82
IMAGE_FETCH_TIMEOUT_SECONDS = 20.0

# Fetch outcome classifier — body-size floor (bytes)
FETCH_MIN_BODY_BYTES = 5_000

# Fetch outcome classifier — cleaned-text floor (chars) for the positive-content
# check, and the script-to-body ratio above which a page is a JS shell
CLEANED_TEXT_MIN_CHARS = 800
SHELL_SCRIPT_RATIO = 0.7

# Embedded structured-data miner (§20 2026-07-07 v2.6): only script bodies at
# least this long are candidate state blobs, and the digest appended to the
# cleaned text is capped at this many chars
EMBEDDED_SCRIPT_MIN_CHARS = 500
EMBEDDED_DATA_MAX_CHARS = 50_000

# Tier-2 (browser) politeness: minimum seconds between fetches to one domain
TIER2_MIN_DELAY_SECONDS = 3.0

# SSRF guard (§16): tier-1 follows redirects manually so each hop can be
# re-screened (scheme + literal host + DNS resolution) before it is followed.
# Over this many hops is a clean fetch error, not an infinite chase.
FETCH_MAX_REDIRECTS = 5

# Tier-3 (managed unblocker) request timeout — the vendor retries/solves
# challenges server-side, so a single request can legitimately take a minute
TIER3_TIMEOUT_SECONDS = 90.0
