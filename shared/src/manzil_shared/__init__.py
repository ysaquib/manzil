"""Manzil shared core: domain models, criteria catalog, scoring engine.

Hard rules (CLAUDE.md): this package is domain-blind (no rental-specific
assumptions in code — rent-domain knowledge lives only in catalog seed data,
tagged by domain) and LLM-free. The scoring engine is pure and deterministic.
"""
