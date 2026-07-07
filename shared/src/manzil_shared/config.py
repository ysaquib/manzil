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

# P3 bounded tool loops
AGENT_MAX_TURNS = 8

# Scheduler sweep: unanswered checkpoints auto-resume after this long
CHECKPOINT_TIMEOUT_HOURS = 24

# VISION input discipline
MAX_IMAGES = 8
IMAGE_MAX_DIM = 1024

# Fetch outcome classifier — body-size floor (bytes)
FETCH_MIN_BODY_BYTES = 5_000

# Fetch outcome classifier — cleaned-text floor (chars) for the positive-content
# check, and the script-to-body ratio above which a page is a JS shell
CLEANED_TEXT_MIN_CHARS = 800
SHELL_SCRIPT_RATIO = 0.7

# Tier-2 (browser) politeness: minimum seconds between fetches to one domain
TIER2_MIN_DELAY_SECONDS = 3.0

# Tier-3 (managed unblocker) request timeout — the vendor retries/solves
# challenges server-side, so a single request can legitimately take a minute
TIER3_TIMEOUT_SECONDS = 90.0
