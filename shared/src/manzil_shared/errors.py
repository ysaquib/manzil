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


class FetchProviderError(ManzilError):
    """A managed fetch provider's own API refused the request — bad zone,
    unauthorized key, suspended account, exhausted plan — before it ever reached
    the target. Distinct from every other fetch failure because the target page
    said nothing: attributing this status to the listing URL sends the reader
    hunting for an anti-bot wall that is not there.

    `retryable` splits the two shapes. A rejection of the *request* (400/401/
    402/403) is deterministic — retrying spends credits to be told the same
    thing four more times — so FETCH raises it fatally with the provider's own
    reason. Provider-side congestion (429, 5xx) is ordinary transience.
    """

    def __init__(
        self,
        provider: str,
        *,
        status: int | None,
        reason: str,
        retryable: bool,
        remedy: str | None = None,
    ) -> None:
        where = f"HTTP {status}" if status is not None else "configuration"
        message = f"{provider} API rejected the request ({where}): {reason}"
        if remedy:
            message += f" — {remedy}"
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.reason = reason
        self.retryable = retryable


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
