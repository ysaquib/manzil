"""Calendar-window helpers shared by operational analytics endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import status

from manzil_api.exceptions import ManzilAPIError


class InvalidAnalyticsTimezone(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_timezone"


def analytics_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidAnalyticsTimezone(f"{name!r} is not a valid IANA timezone") from exc


def calendar_window(
    days: int,
    timezone: str,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime, list[date]]:
    """Return UTC bounds and every local calendar label, including today."""
    zone = analytics_timezone(timezone)
    current = (now or datetime.now(UTC)).astimezone(zone)
    first = current.date() - timedelta(days=days - 1)
    start = datetime.combine(first, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(current.date() + timedelta(days=1), time.min, tzinfo=zone).astimezone(
        UTC
    )
    return start, end, [first + timedelta(days=offset) for offset in range(days)]
