"""Tunables — single home, no magic numbers in stage code (IMPLEMENTATION.md §3).

The single-home rule is settled; every value is a starting point expected to
be tuned against Phase 0 reality (tune freely, changelog-note the change).
"""

# VERIFY check 1 — evidence audit (rapidfuzz partial_ratio)
EVIDENCE_FUZZY_THRESHOLD = 85

# RECONCILE rung 2 — numeric tolerance collapse (percent)
RENT_AGREE_PCT = 3.0
SQFT_AGREE_PCT = 5.0
RECONCILE_SUPERMAJORITY = 2 / 3
ESCALATION_MAX_SIBLING_ROUNDS = 1
ESCALATION_MAX_SIBLING_SOURCES = 3

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
# DISCOVER has its own tighter budgets because each turn uses the judgment-tier
# model and may invoke paid native web search. OpenRouter's server tool also has
# an independent per-request search budget; both limits are required.
DISCOVER_MAX_TURNS = 6
DISCOVER_MAX_SEARCHES = 3
DISCOVER_MAX_RESULTS_PER_SEARCH = 5
DISCOVER_MAX_TOTAL_RESULTS = 12
# Anthropic native web search is $10 / 1,000 successful searches (2026-07-21).
# Live OpenRouter calls prefer the provider-reported total; replay uses this
# explicit price so jobs.cost_actual_usd does not silently omit search spend.
DISCOVER_WEB_SEARCH_REQUEST_USD = 0.01
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
    "DISCOVER": 0.04,  # judgment call + up to 3 native searches
    "IMAGE_FETCH": 0.0,
    "IMAGE_CLASSIFY": 0.005,
    "VISION": 0.03,
    "VERIFY": 0.01,
    "RECONCILE": 0.005,
    "ENRICH": 0.005,  # one small review-synthesis call; Maps calls carry no LLM cost
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

# Scheduler tick (P3-9 lands the scaffold; P3-11/P3-12 add duties): how often
# the worker loop runs its scheduled duties. The first duty is the
# utility-baselines sweep (§9.5, §14: 120-day metro TTL).
SCHEDULER_TICK_SECONDS = 60.0
UTILITY_BASELINE_TTL_DAYS = 120
# A metro whose baselines pass failed is not retried before this cooldown —
# without it a persistently failing pass would fire one live LLM call per tick.
UTILITY_BASELINE_RETRY_SECONDS = 3600.0

# P3-7a2 image discipline. Classification sees the complete stored gallery as
# cheap ≤384 px in-memory thumbnails; quality VISION sees only deterministic
# profile-selected 1024 px targets. The quotas deliberately sum to no more than
# MAX_VISION_TARGET_IMAGES.
MAX_STORED_IMAGES = 30
MAX_IMAGE_CLASSIFY_IMAGES = 30
MAX_VISION_TARGET_IMAGES = 8
VISION_TARGET_QUOTAS = {"kitchen_quality": 3}
IMAGE_CLASSIFY_MAX_DIM = 384
# How many response anomalies IMAGE_CLASSIFY tolerates in one batch before it
# fails closed: at most this many requested hashes may go unanswered, and at
# most this many surplus records (unknown hashes + repeats) may arrive. Beyond
# that the response is not a slightly-lossy batch, it is a malformed one.
IMAGE_CLASSIFY_ANOMALY_TOLERANCE = 2
IMAGE_CLASSIFY_WEBP_QUALITY = 70
IMAGE_PERCEPTUAL_HASH_DISTANCE = 5
IMAGE_MAX_DIM = 1024
IMAGE_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
IMAGE_MAX_PIXELS = 40_000_000
IMAGE_WEBP_QUALITY = 82
IMAGE_FETCH_TIMEOUT_SECONDS = 20.0

# P3-SC5 Floor Plan diagrams. Diagrams carry small labels and dimensions that
# the 1024 px photo profile makes illegible, so they get their own profile and
# their own budget: photo ordering and MAX_STORED_IMAGES must never evict a
# diagram found late in a page, and diagrams must not enlarge the P3-7b
# quality-rating image budget. Unmatched diagrams count against the Property
# cap.
#
# Fixed by the §7.5 legibility comparison (IMPLEMENTATION §P3-SC5), which found
# the *dimension* carries legibility and the *quality* barely moves it: on a
# 2400 px source sheet an 8 pt dimension string survives as 10.2 px at the
# photo profile and 20.5 px at 2048. Raising quality from 82 to 95 cut mean
# error only 0.91 → 0.79 while costing 14 KB → 106 KB per diagram, and lossless
# cost 412 KB — real money against the Supabase free-tier ceiling (§17 R9) for a
# difference invisible at these glyph sizes. So: more pixels, ordinary quality.
DIAGRAM_MAX_DIM = 2048
DIAGRAM_WEBP_QUALITY = 82
DIAGRAM_NORMALIZATION_PROFILE = "webp-2048-q82-v1"
MAX_FLOOR_PLAN_DIAGRAMS_PER_PLAN = 3
MAX_FLOOR_PLAN_DIAGRAMS_PER_PROPERTY = 30

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
EMBEDDED_DATA_MAX_CHARS = 100_000

# Tier-2 (browser) politeness: minimum seconds between fetches to one domain
TIER2_MIN_DELAY_SECONDS = 3.0

# SSRF guard (§16): tier-1 follows redirects manually so each hop can be
# re-screened (scheme + literal host + DNS resolution) before it is followed.
# Over this many hops is a clean fetch error, not an infinite chase.
FETCH_MAX_REDIRECTS = 5

# Tier-3 (managed unblocker) request timeout — the vendor retries/solves
# challenges server-side, so a single request can legitimately take a minute
TIER3_TIMEOUT_SECONDS = 90.0
