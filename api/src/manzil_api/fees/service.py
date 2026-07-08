"""Fees service — upsert on `(hunt_listing_id, fee_slot)`, then enqueue one
hunt-level rescore job (rescore-on-mutation, plan §1.7). Stub for P1-8."""

from __future__ import annotations
