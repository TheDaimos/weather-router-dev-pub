"""Provider-neutral normalization for Lightning consumer semantics."""

from __future__ import annotations

import math
from typing import Any


_NEAREST_VALUE_INTENTS = {
    "weather.lightning.observed.nearest_distance": {
        "quantity": "distance",
        "unit": "km",
        "temporal_meaning": "nearest_event_within_20_minute_window",
    },
    "weather.lightning.observed.nearest_azimuth": {
        "quantity": "azimuth",
        "unit": "°",
        "temporal_meaning": "nearest_event_within_20_minute_window",
    },
}

_RESOURCE_SEMANTICS = {
    "weather.lightning.density": {
        "lightning_semantic_class": "observed_lightning_density_grid",
        "temporal_meaning": "provider_product_frames",
    },
    "weather.lightning.observed.density": {
        "lightning_semantic_class": "observed_lightning_density_grid",
        "temporal_meaning": "10_minute_observed_density",
        "density_unit": "km^-2 min^-1",
        "aggregation_seconds": 600,
    },
    "weather.lightning.observed.events": {
        "lightning_semantic_class": "terrestrial_network_lightning_event",
        "temporal_meaning": "events_within_20_minute_query_window",
        "ground_strike_only": False,
    },
    "weather.lightning.satellite.glm_east.lcfa": {
        "lightning_semantic_class": "satellite_total_lightning_l2_lcfa_file",
        "temporal_meaning": "latest_l2_lcfa_product_file",
        "ground_strike_confirmation": False,
    },
    "weather.lightning.satellite.glm_west.lcfa": {
        "lightning_semantic_class": "satellite_total_lightning_l2_lcfa_file",
        "temporal_meaning": "latest_l2_lcfa_product_file",
        "ground_strike_confirmation": False,
    },
    "weather.lightning.satellite.mtg_li.accumulated_flashes": {
        "lightning_semantic_class": "satellite_total_lightning_accumulation_raster",
        "temporal_meaning": "provider_accumulated_near_real_time_frames",
        "ground_strike_confirmation": False,
    },
}

_DISTANCE_UNITS = {"km", "kilometer", "kilometers", "kilometre", "kilometres"}
_AZIMUTH_UNITS = {"°", "deg", "degree", "degrees"}


def normalize_lightning_value(
    public_id: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Normalize Lightning-derived numeric values without inventing an event.

    None is preserved as the explicit no-event-in-window state. Any present
    value must be a finite number in the supported physical range/unit.
    """
    semantics = _NEAREST_VALUE_INTENTS.get(public_id)
    if semantics is None:
        return dict(entry)

    value = dict(entry)
    raw = value.get("value")
    raw_unit = str(value.get("unit") or "").strip().lower()

    value["quantity"] = semantics["quantity"]
    value["temporal_meaning"] = semantics["temporal_meaning"]
    value["unit"] = semantics["unit"]

    if raw is None:
        value["event_present"] = False
        return value

    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{public_id} returned a non-numeric Lightning value")

    numeric = float(raw)
    if not math.isfinite(numeric):
        raise ValueError(f"{public_id} returned a non-finite Lightning value")

    if public_id.endswith("nearest_distance"):
        if raw_unit not in _DISTANCE_UNITS:
            raise ValueError(
                f"{public_id} returned unsupported distance unit {entry.get('unit')!r}"
            )
        if numeric < 0:
            raise ValueError(f"{public_id} returned a negative distance")
    else:
        if raw_unit not in _AZIMUTH_UNITS:
            raise ValueError(
                f"{public_id} returned unsupported azimuth unit {entry.get('unit')!r}"
            )
        if numeric < 0 or numeric >= 360:
            raise ValueError(f"{public_id} returned azimuth outside [0, 360)")

    value["value"] = numeric
    value["event_present"] = True
    return value


def apply_lightning_resource_semantics(
    public_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Add public Lightning semantics to normalized non-value resources."""
    semantics = _RESOURCE_SEMANTICS.get(public_id)
    if semantics is None:
        return dict(payload)

    value = dict(payload)
    for key, item in semantics.items():
        value[key] = item

    if public_id == "weather.lightning.observed.events":
        window_seconds = value.get("window_seconds")
        if isinstance(window_seconds, bool) or not isinstance(window_seconds, int):
            raise ValueError(f"{public_id} returned no valid event window")
        if window_seconds != 1200:
            raise ValueError(
                f"{public_id} returned unexpected event window {window_seconds!r}"
            )

    return value
