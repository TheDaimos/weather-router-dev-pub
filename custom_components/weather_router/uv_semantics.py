"""Provider-neutral normalization for terrestrial UV-index point semantics."""

from __future__ import annotations

from typing import Any


_UV_INTENTS = {
    "weather.point.uv_index": {
        "sky_condition": "all_sky_or_cloud_affected",
        "temporal_meaning": "current_or_near_current_forecast",
    },
    "weather.point.uv_index_clear_sky": {
        "sky_condition": "clear_sky",
        "temporal_meaning": "current_or_near_current_forecast",
    },
    "weather.point.uv_index_max_today": {
        "sky_condition": "all_sky_or_cloud_affected",
        "temporal_meaning": "maximum_for_local_day_today",
    },
    "weather.point.uv_index_clear_sky_max_today": {
        "sky_condition": "clear_sky",
        "temporal_meaning": "maximum_for_local_day_today",
    },
}

_DIMENSIONLESS_UNITS = {
    "",
    "1",
    "dimensionless",
    "index",
    "uvindex",
    "uv_index",
}


def normalize_uv_index_value(
    public_id: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Normalize one terrestrial UV-index value.

    Only the four explicit terrestrial UV public capabilities are touched.
    UV index is dimensionless and normalized to the canonical unit ``1``.
    """
    if public_id not in _UV_INTENTS:
        return dict(entry)

    value = dict(entry)
    raw = value.get("value")
    if raw is None:
        raise ValueError(f"{public_id} returned no numeric UV-index value")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{public_id} returned a non-numeric UV-index value")

    numeric = float(raw)
    if numeric < 0:
        raise ValueError(f"{public_id} returned a negative UV-index value")

    raw_unit = value.get("unit")
    normalized_unit = str(raw_unit or "").strip().lower().replace(" ", "")
    if normalized_unit not in _DIMENSIONLESS_UNITS:
        raise ValueError(
            f"{public_id} returned unsupported UV-index unit {raw_unit!r}"
        )

    semantics = _UV_INTENTS[public_id]
    value["value"] = numeric
    value["unit"] = "1"
    value["sky_condition"] = semantics["sky_condition"]
    value["temporal_meaning"] = semantics["temporal_meaning"]
    return value
