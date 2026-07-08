"""Jobs service — read jobs, guard state transitions (cancel: queued/running/
waiting_user; retry: failed/cancelled), resume parked checkpoints (P1-7/P1-13). Stub."""

from __future__ import annotations
