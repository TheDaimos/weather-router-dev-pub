"""Provider-neutral value normalization for shared wind point intents."""

from __future__ import annotations

from typing import Any


_SHARED_SPEED_INTENTS = {
    "weather.point.wind_speed",
    "weather.point.wind_gusts",
}
_SHARED_DIRECTION_INTENTS = {
    "weather.point.wind_direction",
}


def _numeric_value(public_id: str, raw: Any) -> float:
    """Return one finite-shape numeric value or fail closed."""
    if raw is None:
        raise ValueError(f"{public_id} returned no numeric wind value")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{public_id} returned a non-numeric wind value")
    return float(raw)


def normalize_shared_wind_value(
    public_id: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Normalize shared wind point values to their public canonical units.

    Specialized capabilities keep provider-native values. Only provider-neutral
    shared point intents are normalized here.
    """
    value = dict(entry)

    if public_id in _SHARED_SPEED_INTENTS:
        raw = _numeric_value(public_id, value.get("value"))
        unit = value.get("unit")
        normalized_unit = str(unit or "").strip().lower().replace(" ", "")
        if normalized_unit in {"m/s", "mps", "ms-1", "m*s-1"}:
            converted = raw
        elif normalized_unit in {"km/h", "kmh", "kmh-1", "km*h-1"}:
            converted = raw / 3.6
        else:
            raise ValueError(
                f"{public_id} returned unsupported wind unit {unit!r}"
            )
        value["value"] = converted
        value["unit"] = "m/s"
        return value

    if public_id in _SHARED_DIRECTION_INTENTS:
        raw = _numeric_value(public_id, value.get("value"))
        unit = str(value.get("unit") or "").strip().lower()
        if unit not in {"°", "deg", "degree", "degrees"}:
            raise ValueError(
                f"{public_id} returned unsupported direction unit {value.get('unit')!r}"
            )
        value["value"] = raw
        value["unit"] = "°"
        return value

    return value
