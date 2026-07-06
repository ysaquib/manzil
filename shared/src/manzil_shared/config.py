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
