"""Pipeline stages — one module per DESIGN §10.3 stage.

Every stage is an async `(RunState, StageCtx) -> RunState` that persists its
outputs BEFORE the runner advances the cursor (idempotent, resumable — NFR3).
Extraction stages get ZERO tools (security control, §16).
"""
