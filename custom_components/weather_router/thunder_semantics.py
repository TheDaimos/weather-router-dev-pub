"""Provider-neutral normalization for Thunder consumer semantics."""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any


_PROBABILITY_INTENT = "weather.point.thunder_probability"
_CELL_INTENT = "weather.convection.thunderstorm_cells"
_REQUIRED_INTERVAL_SECONDS = 3600

_RESOURCE_SEMANTICS = {
    _CELL_INTENT: {
        "thunder_semantic_class": "convective_thunderstorm_cell_nowcast_raster",
        "temporal_meaning": "provider_nowcast_frames",
    },
}


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{_PROBABILITY_INTENT} returned no valid {field}")
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as err:
        raise ValueError(
            f"{_PROBABILITY_INTENT} returned invalid {field} {value!r}"
        ) from err
    if parsed.tzinfo is None:
        raise ValueError(
            f"{_PROBABILITY_INTENT} returned timezone-naive {field}"
        )
    return parsed


def _interval_seconds(entry: dict[str, Any]) -> int:
    """Return a proven one-hour forecast interval from provider-neutral metadata."""
    period = entry.get("period")
    if period is not None:
        if str(period).strip().lower() != "1h":
            raise ValueError(
                f"{_PROBABILITY_INTENT} returned incompatible forecast period {period!r}"
            )
        return _REQUIRED_INTERVAL_SECONDS

    start_raw = entry.get("interval_start")
    end_raw = entry.get("interval_end")
    start = _parse_timestamp(start_raw, field="interval_start")
    end = _parse_timestamp(end_raw, field="interval_end")
    seconds = (end - start).total_seconds()
    if not math.isfinite(seconds) or seconds != _REQUIRED_INTERVAL_SECONDS:
        raise ValueError(
            f"{_PROBABILITY_INTENT} returned incompatible interval {seconds!r} seconds"
        )
    return _REQUIRED_INTERVAL_SECONDS


def normalize_thunder_value(
    public_id: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Normalize the hardened one-hour thunder-probability value contract."""
    if public_id != _PROBABILITY_INTENT:
        return dict(entry)

    value = dict(entry)
    raw = value.get("value")
    if raw is None:
        raise ValueError(f"{public_id} returned no thunder-probability value")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{public_id} returned a non-numeric thunder probability")

    numeric = float(raw)
    if not math.isfinite(numeric) or numeric < 0 or numeric > 100:
        raise ValueError(
            f"{public_id} returned thunder probability outside [0, 100]"
        )

    raw_unit = str(value.get("unit") or "").strip()
    if raw_unit != "%":
        raise ValueError(
            f"{public_id} returned unsupported thunder-probability unit "
            f"{value.get('unit')!r}"
        )

    interval_seconds = _interval_seconds(value)

    value["value"] = numeric
    value["unit"] = "%"
    value["quantity"] = "thunderstorm_probability"
    value["interval_seconds"] = interval_seconds
    value["temporal_meaning"] = "next_1_hour_thunder_probability"
    value["thunder_semantic_class"] = (
        "thunderstorm_probability_next_1h_point_forecast"
    )
    return value


def apply_thunder_resource_semantics(
    public_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Attach hardened Thunder semantics to non-value resources."""
    semantics = _RESOURCE_SEMANTICS.get(public_id)
    if semantics is None:
        return dict(payload)

    value = dict(payload)
    value.update(semantics)
    return value
