"""Provider-neutral value normalization for snowfall point semantics."""

from __future__ import annotations

from typing import Any


_SNOWFALL_INTENT = "weather.point.snowfall"


def normalize_snowfall_value(
    public_id: str,
    entry: dict[str, Any],
    provider_result: dict[str, Any],
) -> dict[str, Any]:
    """Validate and enrich the snowfall point value.

    The existing Open-Meteo provider returns current snowfall in centimeters and
    exposes the runtime interval as result["interval"].  The public contract
    therefore preserves a preceding-runtime-interval accumulation instead of
    pretending that snowfall is an instantaneous value or a fixed hourly sum.
    """
    value = dict(entry)
    if public_id != _SNOWFALL_INTENT:
        return value

    raw = value.get("value")
    if raw is None:
        raise ValueError(f"{public_id} returned no numeric snowfall value")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{public_id} returned a non-numeric snowfall value")

    unit = str(value.get("unit") or "").strip().lower()
    if unit not in {"cm", "centimeter", "centimeters", "centimetre", "centimetres"}:
        raise ValueError(
            f"{public_id} returned unsupported snowfall unit {value.get('unit')!r}"
        )

    interval = provider_result.get("interval")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)):
        raise ValueError(
            f"{public_id} returned no numeric provider runtime interval"
        )
    interval_seconds = float(interval)
    if interval_seconds <= 0:
        raise ValueError(
            f"{public_id} returned invalid provider runtime interval {interval!r}"
        )

    value["value"] = float(raw)
    value["unit"] = "cm"
    value["accumulation_period"] = "preceding_runtime_interval"
    value["interval_seconds"] = (
        int(interval_seconds)
        if interval_seconds.is_integer()
        else interval_seconds
    )
    return value
