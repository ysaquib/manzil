"""Admin operations run outside the pipeline (service-role, no RLS).

These are deliberate, human-invoked corrections to global facts — the kind the
worker's automatic stages must never take on their own. `split_property` is the
reversal half of DEDUPE (P3-4): unmerge a wrongly merged Property so a bad merge
never permanently poisons the globally shared facts every Hunt reads (§17 R5).
"""

from __future__ import annotations

from manzil_worker.ops.split_property import SplitError, SplitResult, split_property

__all__ = ["SplitError", "SplitResult", "split_property"]
