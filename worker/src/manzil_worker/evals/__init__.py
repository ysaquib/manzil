"""Eval harness (P0-11..P0-13, DESIGN §19, IMPLEMENTATION §5).

Bench fixtures live in `worker/tests/fixtures/bench/` (manifest.md +
labels/{slug}.json); generated reports land in `worker/evals/reports/`.
Workflow mode only in Phase 0 (L0); agents mode plugs into the same harness
from L1.
"""
