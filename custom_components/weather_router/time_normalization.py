"""Explicit, pure UTC normalization for WeatherRouter provider data.

No naive local timestamp is interpreted as UTC. Numeric epochs require a
source-declared unit. Calendar dates and durations are not observations.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("unknown_time_zone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def iso_instant(value: Any) -> str | None:
    """Parse timezone-aware ISO/RFC3339 instants only."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return utc_iso(parsed)
    except (ValueError, OverflowError, TypeError):
        return None


def epoch_instant(value: Any, *, unit: str) -> str | None:
    """Never guess seconds vs milliseconds. Provider must declare unit."""
    if unit not in ("seconds", "milliseconds"):
        raise ValueError("undeclared_epoch_unit")
    if type(value) not in (int, float) or not isfinite(value):
        return None
    try:
        instant = datetime.fromtimestamp(
            value / (1000 if unit == "milliseconds" else 1), tz=UTC)
        return utc_iso(instant)
    except (ValueError, OverflowError, OSError):
        return None


def provider_local_instant(value: Any, *, iana_zone: str) -> str | None:
    """Convert proven IANA-local datetime; reject gaps and ambiguous times."""
    if not isinstance(value, str) or not isinstance(iana_zone, str):
        return None
    try:
        naive = datetime.fromisoformat(value.strip())
        if naive.tzinfo is not None:
            return utc_iso(naive)
        zone = ZoneInfo(iana_zone)
        a = naive.replace(tzinfo=zone, fold=0)
        b = naive.replace(tzinfo=zone, fold=1)
        # Both DST folds are allowed only if they resolve to one UTC instant.
        if a.utcoffset() != b.utcoffset():
            return None
        utc = a.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) != naive:
            return None
        return utc_iso(utc)
    except (ValueError, ZoneInfoNotFoundError, OverflowError):
        return None


def rss_instant(value: Any) -> str | None:
    """RFC2822 timestamps require a concrete numeric/named zone."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return utc_iso(parsed)
    except (ValueError, TypeError, OverflowError, IndexError):
        return None


def wms_time_values(raw: Any, *, max_values: int = 256) -> list[str]:
    """Expand bounded explicit ISO instants or ISO start/end/PTnH/PTnM.

    Unspecified zone, daily date-only, and unbounded/invalid intervals fail
    closed; no point-in-time freshness is inferred from a day product.
    """
    if not isinstance(raw, str) or not raw.strip():
        return []
    output: list[str] = []
    for item in raw.split(","):
        parts = item.strip().split("/")
        if len(parts) == 1:
            instant = iso_instant(parts[0])
            if instant is None:
                return []
            output.append(instant)
        elif len(parts) == 3:
            first, last = iso_instant(parts[0]), iso_instant(parts[1])
            cadence = parts[2]
            import re
            match = re.fullmatch(r"PT([1-9][0-9]*)(M|H)", cadence)
            if not first or not last or not match:
                return []
            count = int(match.group(1))
            step = timedelta(minutes=count) if match.group(2) == "M" else timedelta(hours=count)
            a = datetime.fromisoformat(first.replace("Z", "+00:00"))
            b = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if a > b:
                return []
            while a <= b:
                if len(output) >= max_values:
                    return []
                output.append(utc_iso(a))
                a += step
        else:
            return []
        if len(output) > max_values:
            return []
    return output


def calendar_day_interval(value: Any, *, iana_zone: str) -> tuple[str, str] | None:
    """UTC bounds of a local calendar day; never fabricate observation time."""
    if not isinstance(value, str):
        return None
    try:
        selected = date.fromisoformat(value)
        zone = ZoneInfo(iana_zone)
        start = datetime(selected.year, selected.month, selected.day, tzinfo=zone)
        next_day = selected + timedelta(days=1)
        end = datetime(next_day.year, next_day.month, next_day.day, tzinfo=zone)
        return utc_iso(start), utc_iso(end)
    except (ValueError, ZoneInfoNotFoundError, OverflowError):
        return None
