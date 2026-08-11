"""Probe access lines are dropped, everything else survives.

Render sets the health-check cadence and does not expose it as a setting, so
the fix for a log full of `GET /v1/health` is on our side of the wire: filter
the successful ones out of `uvicorn.access` (§20 2026-08-11).
"""

from __future__ import annotations

import logging

import pytest
from manzil_api.probe_logging import SuccessfulProbeFilter, quiet_probe_access_logs


def _access_record(path: str, status: int) -> logging.LogRecord:
    """The shape uvicorn.access emits: '%s - "%s %s HTTP/%s" %d'."""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("10.0.0.1:443", "GET", path, "1.1", status),
        exc_info=None,
    )


@pytest.mark.parametrize(
    ("path", "status", "kept"),
    [
        ("/v1/health", 200, False),
        ("/v1/ready", 200, False),
        ("/v1/ready?verbose=1", 200, False),  # query strings do not smuggle it through
        ("/v1/health", 500, True),  # a failing probe is the whole point of the probe
        ("/v1/ready", 503, True),
        ("/v1/hunts", 200, True),  # ordinary traffic is untouched
    ],
)
def test_only_successful_probes_are_dropped(path: str, status: int, kept: bool) -> None:
    assert SuccessfulProbeFilter().filter(_access_record(path, status)) is kept


def test_an_unexpected_record_shape_is_kept() -> None:
    """Reading positional args couples this to uvicorn's format string. If that
    changes, lose the filtering, never the log line."""
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="something else entirely",
        args=None,
        exc_info=None,
    )
    assert SuccessfulProbeFilter().filter(record) is True


def test_attaching_is_idempotent_and_opt_outable(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = logging.getLogger("uvicorn.access")
    for existing in list(logger.filters):
        logger.removeFilter(existing)
    try:
        monkeypatch.setenv("MANZIL_LOG_PROBE_REQUESTS", "true")
        quiet_probe_access_logs()
        assert logger.filters == []

        monkeypatch.delenv("MANZIL_LOG_PROBE_REQUESTS")
        quiet_probe_access_logs()
        quiet_probe_access_logs()
        assert sum(isinstance(f, SuccessfulProbeFilter) for f in logger.filters) == 1
    finally:
        for existing in list(logger.filters):
            logger.removeFilter(existing)
