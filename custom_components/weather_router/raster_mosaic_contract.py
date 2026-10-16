"""P7-010: strict validation of a proposed, separate Consumer raster mosaic V2 request.

Not registered as a websocket command. Consumer API V1 remains untouched.
No provider selection, network access, image processing or implicit credentials.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Mapping


class MosaicContractError(ValueError):
    """Invalid opt-in mosaic request; never fall back to a V1 interpretation."""


def _number(value: Any, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MosaicContractError("coordinate must be a finite number")
    number = float(value)
    if not isfinite(number) or not minimum <= number <= maximum:
        raise MosaicContractError("coordinate is outside valid geographic range")
    return number


def _bounded_int(value: Any, minimum: int, maximum: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MosaicContractError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise MosaicContractError(f"{field} is outside allowed limits")
    return value


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MosaicContractError(f"{field} must be an object")
    return value


def _keys(value: Mapping[str, Any], allowed: set[str], required: set[str], field: str) -> None:
    if not required.issubset(value) or set(value) - allowed:
        raise MosaicContractError(f"missing or unexpected {field} fields")


def _utc(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise MosaicContractError(f"{field} must be an offset-aware ISO time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise MosaicContractError(f"invalid {field}") from err
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MosaicContractError(f"{field} must contain a timezone")
    return parsed.isoformat()


def validate_raster_mosaic_request(raw: Any) -> dict[str, Any]:
    """Normalize one explicit V2 proposal without relaxing existing V1 rules."""
    value = _mapping(raw, "request")
    _keys(value, {"type", "contract_version", "capability", "profile_id", "consumer_id", "correlation_id",
                  "context", "time", "limits"},
          {"type", "contract_version", "capability", "context", "time", "limits"},
          "request")
    if (value["type"] != "weather_router/consumer/resolve_mosaic"
            or type(value["contract_version"]) is not int
            or value["contract_version"] != 2
            or value["capability"] != "weather.precipitation.layer"):
        raise MosaicContractError("unsupported V2 mosaic contract")
    context = _mapping(value["context"], "context")
    _keys(context, {"type", "west", "south", "east", "north", "focus"},
          {"type", "west", "south", "east", "north"}, "context")
    if context["type"] != "bbox":
        raise MosaicContractError("mosaic context must be bbox")
    viewport = {field: _number(context[field], low, high)
                for field, low, high in (("west", -180, 180), ("south", -90, 90),
                                         ("east", -180, 180), ("north", -90, 90))}
    if viewport["north"] <= viewport["south"] or viewport["west"] == viewport["east"]:
        raise MosaicContractError("degenerate bbox")
    viewport["type"] = "bbox"
    if "focus" in context:
        focus = _mapping(context["focus"], "focus")
        _keys(focus, {"latitude", "longitude"}, {"latitude", "longitude"}, "focus")
        viewport["focus"] = {
            "latitude": _number(focus["latitude"], -90, 90),
            "longitude": _number(focus["longitude"], -180, 180),
        }
    temporal = _mapping(value["time"], "time")
    _keys(temporal, {"mode", "max_data_age_seconds", "max_time_delta_seconds",
                     "target_time"}, {"mode", "max_data_age_seconds"}, "time")
    mode = temporal["mode"]
    if mode not in {"latest_coherent", "at_time"}:
        raise MosaicContractError("unsupported temporal mode")
    time: dict[str, Any] = {
        "mode": mode,
        "max_data_age_seconds": _bounded_int(temporal["max_data_age_seconds"],
                                               1, 86400, "max_data_age_seconds"),
    }
    if "max_time_delta_seconds" in temporal:
        time["max_time_delta_seconds"] = _bounded_int(
            temporal["max_time_delta_seconds"], 0, 86400, "max_time_delta_seconds")
    if mode == "at_time":
        if "target_time" not in temporal:
            raise MosaicContractError("at_time requires target_time")
        time["target_time"] = _utc(temporal["target_time"], "target_time")
    elif "target_time" in temporal:
        raise MosaicContractError("latest_coherent cannot set target_time")
    limits = _mapping(value["limits"], "limits")
    _keys(limits, {"max_layers", "max_tile_requests"},
          {"max_layers", "max_tile_requests"}, "limits")
    bounded_limits = {
        "max_layers": _bounded_int(limits["max_layers"], 1, 12, "max_layers"),
        "max_tile_requests": _bounded_int(
            limits["max_tile_requests"], 1, 256, "max_tile_requests"),
    }
    result: dict[str, Any] = {
        "type": value["type"], "contract_version": 2,
        "capability": value["capability"], "context": viewport,
        "time": time, "limits": bounded_limits,
    }
    if "profile_id" in value:
        profile_id = value["profile_id"]
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise MosaicContractError("invalid profile_id")
        result["profile_id"] = profile_id
    for meta_field, max_length in (("consumer_id", 96), ("correlation_id", 128)):
        if meta_field in value:
            meta_value = value[meta_field]
            if not isinstance(meta_value, str) or not meta_value or len(meta_value) > max_length:
                raise MosaicContractError("invalid " + meta_field)
            result[meta_field] = meta_value
    return result
