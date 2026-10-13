"""Provider-neutral value normalization for visibility and fog point semantics."""

from __future__ import annotations

from typing import Any


_VISIBILITY_DISTANCE_INTENTS = {
    "weather.point.visibility",
    "weather.observation.visibility",
}
_FOG_FRACTION_INTENT = "weather.point.fog"


def _numeric_value(public_id: str, raw: Any) -> float:
    """Return one numeric value or fail closed."""
    if raw is None:
        raise ValueError(f"{public_id} returned no numeric visibility value")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{public_id} returned a non-numeric visibility value")
    return float(raw)


def normalize_visibility_value(
    public_id: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Normalize visibility/fog values to their public canonical units.

    Visibility distance is returned in meters. Fog fraction remains a percentage.
    Unrelated specialized point values are returned unchanged.
    """
    value = dict(entry)

    if public_id in _VISIBILITY_DISTANCE_INTENTS:
        raw = _numeric_value(public_id, value.get("value"))
        unit = value.get("unit")
        normalized_unit = str(unit or "").strip().lower().replace(" ", "")
        if normalized_unit in {"m", "meter", "meters", "metre", "metres"}:
            converted = raw
        elif normalized_unit in {"km", "kilometer", "kilometers", "kilometre", "kilometres"}:
            converted = raw * 1000.0
        else:
            raise ValueError(
                f"{public_id} returned unsupported visibility unit {unit!r}"
            )
        value["value"] = converted
        value["unit"] = "m"
        return value

    if public_id == _FOG_FRACTION_INTENT:
        raw = _numeric_value(public_id, value.get("value"))
        unit = str(value.get("unit") or "").strip().lower()
        if unit not in {"%", "percent", "percentage"}:
            raise ValueError(
                f"{public_id} returned unsupported fog fraction unit {value.get('unit')!r}"
            )
        value["value"] = raw
        value["unit"] = "%"
        return value

    return value
