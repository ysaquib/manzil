"""Access-log quieting for uptime probes.

Render health-checks `/v1/health` on a fixed cadence it does not expose as a
setting, so the probe interval is not ours to change — but the *log* is. Every
successful probe writes a uvicorn access line, and at Render's cadence those
lines are the overwhelming majority of production output: the signal an
operator actually came for scrolls away between heartbeats.

So: drop access lines for the probe routes when, and only when, they succeeded.
A probe that fails or errors is exactly the event the health check exists to
announce and is always logged. Set `MANZIL_LOG_PROBE_REQUESTS=true` to keep
every line (debugging a probe that Render reports failing but the service
thinks is fine).

Only the access log is touched. Nothing here filters application logging, and a
request that raises still reaches the error log through the normal path.
"""

from __future__ import annotations

import logging
import os

# Liveness and readiness. `/v1/ready` is included because Render (or an uptime
# monitor) may poll it just as often; its failures carry a 503 and survive.
PROBE_PATHS = frozenset({"/v1/health", "/v1/ready"})


class SuccessfulProbeFilter(logging.Filter):
    """Drops `uvicorn.access` records for successful probe requests.

    Uvicorn logs access lines as `'%s - "%s %s HTTP/%s" %d'` with args
    `(client_addr, method, path, http_version, status_code)`. Reading positional
    args is coupled to that format, so every access is defensive: an unexpected
    record shape keeps the line rather than swallowing it.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        path, status = args[2], args[4]
        if not isinstance(path, str) or not isinstance(status, int):
            return True
        return not (path.split("?", 1)[0] in PROBE_PATHS and status < 400)


def quiet_probe_access_logs() -> None:
    """Attach the filter to `uvicorn.access` unless probe logging is requested.

    Idempotent — repeated calls (app factory in tests, reload workers) leave one
    filter attached.
    """
    if os.environ.get("MANZIL_LOG_PROBE_REQUESTS", "").strip().lower() in ("1", "true", "yes"):
        return
    logger = logging.getLogger("uvicorn.access")
    if any(isinstance(existing, SuccessfulProbeFilter) for existing in logger.filters):
        return
    logger.addFilter(SuccessfulProbeFilter())
