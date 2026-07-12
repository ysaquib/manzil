"""Exception taxonomy (IMPLEMENTATION.md §2 — proposal status).

Stages raise these; the runner maps them to job outcomes. Names and
granularity follow what the runner actually needs and may churn.
"""

from __future__ import annotations

from manzil_shared.models import CheckpointPrompt


class ManzilError(Exception):
    """Base class for all Manzil-specific errors."""


class StageRetryable(ManzilError):
    """Transient stage failure: runner retries with backoff."""


class StageFatal(ManzilError):
    """Unrecoverable stage failure: job -> failed."""


class PrivateAddressRefused(ManzilError):
    """SSRF guard (§16): a fetch target's host resolved to (or is) a non-global
    IP — private/loopback/link-local/etc. Raised in the fetch layer before any
    connect and re-checked on every redirect hop, so neither a pasted URL nor a
    model-controlled `fetch_page` call can steer the worker at internal
    infrastructure. Subclasses ManzilError, so the runner maps a submission-path
    refusal to a clean job failure; the tool loop surfaces it as a tool error."""


class FetchBlocked(ManzilError):
    """Fetch outcome `blocked`: escalate tier and record in the adapter registry."""


class FetchShell(ManzilError):
    """Fetch outcome `shell` (JS-shell page): escalate one tier."""


class ExtractionInvalid(ManzilError):
    """Extraction failed schema validation: one corrective retry, then fatal."""


class AgentBudgetExceeded(ManzilError):
    """Agents mode: turn budget exhausted; the stage decides the fallback."""


class CheckpointRaised(ManzilError):
    """Stage paused into a checkpoint: runner persists prompt -> `waiting_user`."""

    def __init__(self, prompt: CheckpointPrompt) -> None:
        super().__init__(prompt.question)
        self.prompt = prompt
