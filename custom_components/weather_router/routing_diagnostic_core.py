"""Pure core for WeatherRouter routing diagnostics.

No Home Assistant imports are used here so redaction, resource summaries and the trace
format can be regression-tested in isolation. The admin-only runtime store lives in
routing_diagnostics.py.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from math import isfinite
import re
from time import monotonic
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

ROUTING_DIAGNOSTIC_SCHEMA = "weather_router.routing_diagnostic.v1"
ROUTING_DIAGNOSTIC_INDEX_SCHEMA = "weather_router.routing_diagnostics.index.v1"
ROUTING_DIAGNOSTIC_LIMIT = 50
_MAX_STRING = 4000
_MAX_LIST = 200
_MAX_DICT = 200

_SECRET_QUERY_KEYS = {
    "api_key", "apikey", "access_token", "token", "key", "appid",
    "password", "secret", "authorization", "signature", "sig",
}
_SECRET_KEY_RE = re.compile(
    r"(?i)(?:api[_-]?key|apikey|access[_-]?token|token|secret|password|"
    r"authorization|cookie|set-cookie|client[_-]?secret|private[_-]?key)"
)
_SECRET_QUERY_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|apikey|access[_-]?token|token|key|appid|password|"
    r"secret|signature|sig)=)[^&#\s]+"
)
_AUTH_RE = re.compile(
    r"(?i)((?:authorization|proxy-authorization)\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+"
)
_COOKIE_RE = re.compile(r"(?i)((?:cookie|set-cookie)\s*[:=]\s*)[^\r\n]+")
_URL_USERINFO_RE = re.compile(r"(?i)(https?://[^:/@\s]+:)[^@/\s]+@")
_TEMPLATE_TOKEN_RE = re.compile(r"\{[a-zA-Z0-9_:-]+\}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def redact_text(value: str) -> str:
    """Redact common credential shapes while retaining diagnostic meaning."""
    text = str(value)
    text = _SECRET_QUERY_RE.sub(r"\1<redacted>", text)
    text = _AUTH_RE.sub(r"\1<redacted>", text)
    text = _COOKIE_RE.sub(r"\1<redacted>", text)
    text = _URL_USERINFO_RE.sub(r"\1<redacted>@", text)
    return text[:_MAX_STRING]


def diagnostic_value(value: Any, *, depth: int = 0, key: str = "") -> Any:
    """Return bounded JSON-safe diagnostic data with centralized secret redaction."""
    if _SECRET_KEY_RE.search(str(key or "")):
        return "<redacted>"
    if depth > 7:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            return str(value)
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for child_key, child_value in list(value.items())[:_MAX_DICT]:
            name = str(child_key)
            result[name] = diagnostic_value(
                child_value,
                depth=depth + 1,
                key=name,
            )
        if len(value) > _MAX_DICT:
            result["_truncated_keys"] = len(value) - _MAX_DICT
        return result
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        result = [
            diagnostic_value(item, depth=depth + 1)
            for item in items[:_MAX_LIST]
        ]
        if len(items) > _MAX_LIST:
            result.append({"_truncated_items": len(items) - _MAX_LIST})
        return result
    return redact_text(repr(value))


def safe_url_summary(value: Any) -> dict[str, Any] | None:
    """Return a credential-free URL summary, never the full URL."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return {"valid": False}
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {"valid": False}
    query_keys = []
    try:
        for query_key, _query_value in parse_qsl(parsed.query, keep_blank_values=True):
            if query_key.casefold() not in _SECRET_QUERY_KEYS:
                query_keys.append(query_key)
    except ValueError:
        query_keys = []
    tokens = sorted(set(_TEMPLATE_TOKEN_RE.findall(value)))
    return {
        "valid": True,
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "path_segments": len([part for part in parsed.path.split("/") if part]),
        "query_keys": sorted(set(query_keys))[:30],
        "template_tokens": tokens[:30],
        "has_fragment": bool(parsed.fragment),
    }


def _timeline_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    timeline = payload.get("timeline")
    if isinstance(timeline, dict):
        frames = [item for item in timeline.get("frames", []) if isinstance(item, dict)]
    elif isinstance(payload.get("frames"), list):
        frames = [item for item in payload.get("frames", []) if isinstance(item, dict)]
        timeline = payload
    else:
        return None

    times = [
        str(item.get("time"))
        for item in frames
        if item.get("time") is not None
    ]
    intervals: list[float] = []
    parsed: list[datetime] = []
    for value in times:
        try:
            parsed.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            continue
    for previous, current in zip(parsed, parsed[1:]):
        intervals.append((current - previous).total_seconds())

    unique_intervals = sorted(set(round(item, 3) for item in intervals))
    duplicate_times = max(0, len(times) - len(set(times)))
    frame_kinds = sorted(
        {
            str(item.get("kind"))
            for item in frames
            if isinstance(item.get("kind"), str) and item.get("kind")
        }
    )
    return {
        "frame_count": len(frames),
        "first_frame": times[0] if times else None,
        "last_frame": times[-1] if times else None,
        "default": timeline.get("default") if isinstance(timeline, dict) else None,
        "default_index": timeline.get("default_index") if isinstance(timeline, dict) else None,
        "current_index": timeline.get("current_index") if isinstance(timeline, dict) else None,
        "loop": bool(timeline.get("loop")) if isinstance(timeline, dict) and "loop" in timeline else None,
        "frame_kinds": frame_kinds,
        "interval_seconds": unique_intervals[:20],
        "duplicate_times": duplicate_times,
        "invalid_time_count": len(frames) - len(parsed),
    }



def _earthquake_numeric_range(
    events: list[dict[str, Any]],
    field: str,
) -> dict[str, float] | None:
    """Return a finite min/max range from normalized earthquake semantics."""
    values: list[float] = []
    for item in events:
        semantics = item.get("earthquake_semantics")
        if not isinstance(semantics, dict):
            continue
        value = semantics.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
            if isfinite(number):
                values.append(number)
    if not values:
        return None
    return {"min": min(values), "max": max(values)}

def resource_summary(
    resource_type: str,
    payload: dict[str, Any] | None,
    provider_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a small type-aware resource summary without retaining large payloads."""
    payload = payload if isinstance(payload, dict) else {}
    provider_result = provider_result if isinstance(provider_result, dict) else {}
    result: dict[str, Any] = {"type": str(resource_type or "unknown")}

    if resource_type == "raster_tile":
        result.update(
            {
                "tile_url": safe_url_summary(payload.get("tile_url")),
                "tile_size": payload.get("tile_size"),
                "min_zoom": payload.get("min_zoom"),
                "max_zoom": payload.get("max_zoom"),
                "max_native_zoom": payload.get("max_native_zoom"),
                "default_opacity": payload.get("default_opacity"),
                "attribution": redact_text(str(payload.get("attribution") or "")) or None,
                "legend": {
                    "title": payload.get("legend", {}).get("title"),
                    "url": safe_url_summary(payload.get("legend", {}).get("url")),
                    "style": payload.get("legend", {}).get("style"),
                } if isinstance(payload.get("legend"), dict) else None,
                "provider_metadata": diagnostic_value(provider_result.get("provider_metadata")),
                "lightning_semantic_class": payload.get("lightning_semantic_class"),
                "thunder_semantic_class": payload.get("thunder_semantic_class"),
                "temporal_meaning": payload.get("temporal_meaning"),
                "ground_strike_confirmation": payload.get("ground_strike_confirmation"),
                "density_unit": payload.get("density_unit"),
                "aggregation_seconds": payload.get("aggregation_seconds"),
            }
        )
        result["timeline"] = _timeline_summary(payload)
    elif resource_type == "value":
        values = payload.get("values")
        rows = values if isinstance(values, dict) else {}
        result["value_count"] = len(rows)
        result["values"] = {
            str(name): {
                "unit": item.get("unit") if isinstance(item, dict) else None,
                "data_time": item.get("data_time") if isinstance(item, dict) else None,
                "accumulation_period": (
                    item.get("accumulation_period")
                    if isinstance(item, dict)
                    else None
                ),
                "interval_seconds": (
                    item.get("interval_seconds")
                    if isinstance(item, dict)
                    else None
                ),
                "interval_start": (
                    item.get("interval_start")
                    if isinstance(item, dict)
                    else None
                ),
                "interval_end": (
                    item.get("interval_end")
                    if isinstance(item, dict)
                    else None
                ),
                "provider_period": (
                    item.get("period")
                    if isinstance(item, dict)
                    else None
                ),
                "thunder_semantic_class": (
                    item.get("thunder_semantic_class")
                    if isinstance(item, dict)
                    else None
                ),
                "sky_condition": (
                    item.get("sky_condition")
                    if isinstance(item, dict)
                    else None
                ),
                "temporal_meaning": (
                    item.get("temporal_meaning")
                    if isinstance(item, dict)
                    else None
                ),
                "time_source": (
                    item.get("time_source")
                    if isinstance(item, dict)
                    else None
                ),
                "local_day": (
                    item.get("local_day")
                    if isinstance(item, dict)
                    else None
                ),
                "quantity": (
                    item.get("quantity")
                    if isinstance(item, dict)
                    else None
                ),
                "event_present": (
                    item.get("event_present")
                    if isinstance(item, dict)
                    else None
                ),
                "state": (
                    "null"
                    if isinstance(item, dict) and item.get("value") is None
                    else "present"
                    if isinstance(item, dict)
                    else "invalid"
                ),
            }
            for name, item in list(rows.items())[:50]
        }
    elif resource_type in {"event_feed", "hazard_feed"}:
        events = [item for item in payload.get("events", []) if isinstance(item, dict)]
        result.update(
            {
                "event_count": payload.get("event_count", len(events)),
                "unfiltered_event_count": payload.get("unfiltered_event_count"),
                "source_count": payload.get("source_count"),
                "matched_source_count": payload.get("matched_source_count"),
                "filtered": payload.get("filtered"),
                "event_filter": diagnostic_value(payload.get("event_filter")),
                "source_diagnostics": diagnostic_value(
                    payload.get("source_diagnostics")
                ),
                "event_types": sorted(
                    {
                        str(item.get("event_type") or item.get("hazard_type"))
                        for item in events
                        if item.get("event_type") or item.get("hazard_type")
                    }
                )[:50],
                "severities": sorted(
                    {str(item.get("severity")) for item in events if item.get("severity")}
                )[:20],
                "alert_stages": sorted(
                    {str(item.get("alert_stage")) for item in events if item.get("alert_stage")}
                )[:20],
                "tornado_semantic_classes": sorted(
                    {
                        str(item.get("tornado_semantic_class"))
                        for item in events
                        if item.get("tornado_semantic_class")
                    }
                )[:20],
                "hazard_match_scopes": sorted(
                    {
                        str(item.get("hazard_match_scope"))
                        for item in events
                        if item.get("hazard_match_scope")
                    }
                )[:20],
                "hail_semantic_classes": sorted(
                    {
                        str(item.get("hail_semantic_class"))
                        for item in events
                        if item.get("hail_semantic_class")
                    }
                )[:20],
                "hail_match_scopes": sorted(
                    {
                        str(item.get("hail_match_scope"))
                        for item in events
                        if item.get("hail_match_scope")
                    }
                )[:20],
                "wind_hazard_semantic_classes": sorted(
                    {
                        str(item.get("wind_hazard_semantic_class"))
                        for item in events
                        if item.get("wind_hazard_semantic_class")
                    }
                )[:20],
                "wind_hazard_match_scopes": sorted(
                    {
                        str(item.get("wind_hazard_match_scope"))
                        for item in events
                        if item.get("wind_hazard_match_scope")
                    }
                )[:20],
                "supercell_semantic_classes": sorted(
                    {
                        str(item.get("supercell_semantic_class"))
                        for item in events
                        if item.get("supercell_semantic_class")
                    }
                )[:20],
                "supercell_match_scopes": sorted(
                    {
                        str(item.get("supercell_match_scope"))
                        for item in events
                        if item.get("supercell_match_scope")
                    }
                )[:20],
                "flood_semantic_classes": sorted(
                    {
                        str(semantic.get("semantic_class"))
                        for item in events
                        for semantic in (
                            item.get("flood_semantics")
                            if isinstance(item.get("flood_semantics"), list)
                            else []
                        )
                        if isinstance(semantic, dict)
                        and semantic.get("semantic_class")
                    }
                )[:20],
                "flood_match_scopes": sorted(
                    {
                        str(semantic.get("match_scope"))
                        for item in events
                        for semantic in (
                            item.get("flood_semantics")
                            if isinstance(item.get("flood_semantics"), list)
                            else []
                        )
                        if isinstance(semantic, dict)
                        and semantic.get("match_scope")
                    }
                )[:20],
                "tropical_system_classes": sorted(
                    {
                        str(item["tropical_system"].get("system_class"))
                        for item in events
                        if isinstance(item.get("tropical_system"), dict)
                        and item["tropical_system"].get("system_class")
                    }
                )[:20],
                "tropical_regional_terms": sorted(
                    {
                        str(item["tropical_system"].get("regional_term"))
                        for item in events
                        if isinstance(item.get("tropical_system"), dict)
                        and item["tropical_system"].get("regional_term")
                    }
                )[:20],
                "tsunami_semantic_classes": sorted(
                    {str(item["tsunami_semantics"].get("semantic_class")) for item in events if isinstance(item.get("tsunami_semantics"), dict) and item["tsunami_semantics"].get("semantic_class")}
                )[:20],
                "tsunami_alert_stages": sorted(
                    {str(item["tsunami_semantics"].get("alert_stage")) for item in events if isinstance(item.get("tsunami_semantics"), dict) and item["tsunami_semantics"].get("alert_stage")}
                )[:20],
                "tsunami_wave_evidence": sorted(
                    {str(item["tsunami_semantics"].get("wave_evidence")) for item in events if isinstance(item.get("tsunami_semantics"), dict) and item["tsunami_semantics"].get("wave_evidence")}
                )[:20],
                "earthquake_semantic_classes": sorted(
                    {str(item["earthquake_semantics"].get("semantic_class")) for item in events if isinstance(item.get("earthquake_semantics"), dict) and item["earthquake_semantics"].get("semantic_class")}
                )[:20],
                "earthquake_catalog_selections": sorted(
                    {str(item["earthquake_semantics"].get("catalog_selection")) for item in events if isinstance(item.get("earthquake_semantics"), dict) and item["earthquake_semantics"].get("catalog_selection")}
                )[:20],
                "earthquake_magnitude_types": sorted(
                    {str(item["earthquake_semantics"].get("magnitude_type")) for item in events if isinstance(item.get("earthquake_semantics"), dict) and item["earthquake_semantics"].get("magnitude_type")}
                )[:20],
                "earthquake_pager_alerts": sorted(
                    {str(item["earthquake_semantics"].get("pager_alert")) for item in events if isinstance(item.get("earthquake_semantics"), dict) and item["earthquake_semantics"].get("pager_alert")}
                )[:20],
                "earthquake_tsunami_flag_count": sum(
                    1 for item in events
                    if isinstance(item.get("earthquake_semantics"), dict)
                    and item["earthquake_semantics"].get("tsunami_flag") is True
                ),
                "earthquake_magnitude_range": _earthquake_numeric_range(events, "magnitude"),
                "earthquake_depth_km_range": _earthquake_numeric_range(events, "depth_km"),

                "volcano_semantic_classes": sorted(
                    {str(item["volcano_semantics"].get("semantic_class")) for item in events if isinstance(item.get("volcano_semantics"), dict) and item["volcano_semantics"].get("semantic_class")}
                )[:20],
                "volcano_report_types": sorted(
                    {str(item["volcano_semantics"].get("report_type")) for item in events if isinstance(item.get("volcano_semantics"), dict) and item["volcano_semantics"].get("report_type")}
                )[:20],
                "volcano_aviation_color_codes": sorted(
                    {str(item["volcano_semantics"].get("aviation_color_code")) for item in events if isinstance(item.get("volcano_semantics"), dict) and item["volcano_semantics"].get("aviation_color_code")}
                )[:20],
                "volcano_alert_levels": sorted(
                    {str(item["volcano_semantics"].get("volcano_alert_level")) for item in events if isinstance(item.get("volcano_semantics"), dict) and item["volcano_semantics"].get("volcano_alert_level")}
                )[:20],
                "volcano_source_event_types": sorted(
                    {str(item["volcano_semantics"].get("source_event_type")) for item in events if isinstance(item.get("volcano_semantics"), dict) and item["volcano_semantics"].get("source_event_type")}
                )[:20],
                "spatial_filter": diagnostic_value(payload.get("spatial_filter")),
                "geometry_count": sum(1 for item in events if item.get("geometry")),
                "lightning_semantic_class": payload.get("lightning_semantic_class"),
                "temporal_meaning": payload.get("temporal_meaning"),
                "ground_strike_only": payload.get("ground_strike_only"),
                "window_seconds": payload.get("window_seconds"),
                "lightning_types": sorted(
                    {str(item.get("lightning_type")) for item in events if item.get("lightning_type")}
                )[:20],
            }
        )
    elif resource_type == "data_file":
        result.update(
            {
                "format": payload.get("format"),
                "content_type": payload.get("content_type"),
                "size_bytes": payload.get("size_bytes"),
                "transport": payload.get("transport"),
                "url": safe_url_summary(payload.get("url")),
                "data_time": payload.get("data_time"),
                "valid_time": payload.get("valid_time"),
                "forecast_reference_time": payload.get("forecast_reference_time"),
                "lightning_semantic_class": payload.get("lightning_semantic_class"),
                "temporal_meaning": payload.get("temporal_meaning"),
                "ground_strike_confirmation": payload.get("ground_strike_confirmation"),
            }
        )
    elif resource_type == "image_sequence":
        result.update(
            {
                "georeferenced": payload.get("georeferenced"),
                "default_index": payload.get("default_index"),
                "timeline": _timeline_summary(payload),
            }
        )
    elif resource_type == "live_stream":
        result.update(
            {
                "url": safe_url_summary(payload.get("url")),
                "transport": payload.get("transport"),
                "content_type": payload.get("content_type"),
                "title": payload.get("title"),
            }
        )
    elif resource_type == "planetary_tile":
        result.update(
            {
                "body": payload.get("body"),
                "tile_url": safe_url_summary(payload.get("tile_url")),
                "min_zoom": payload.get("min_zoom"),
                "max_zoom": payload.get("max_zoom"),
                "tile_size": payload.get("tile_size"),
                "crs": payload.get("crs"),
            }
        )
    else:
        result["keys"] = sorted(str(key) for key in payload)[:100]

    return diagnostic_value(result)


class RoutingTraceBuilder:
    """Mutable builder for one bounded routing diagnostic trace."""

    def __init__(
        self,
        *,
        capability: str,
        contract_version: int | None,
        caller: str = "weather_router/consumer/resolve",
        build_version: str | None = None,
        loader_revision: str | None = None,
    ) -> None:
        self._started = monotonic()
        self._stage_started: dict[str, float] = {}
        self.trace_id = f"rt-{uuid4().hex[:16]}"
        self.data: dict[str, Any] = {
            "schema": ROUTING_DIAGNOSTIC_SCHEMA,
            "meta": {
                "trace_id": self.trace_id,
                "started_at": utc_now(),
                "completed_at": None,
                "duration_ms": None,
                "consumer_contract_version": contract_version,
                "caller": caller,
                "build_version": build_version,
                "loader_revision": loader_revision,
            },
            "request": {
                "capability": capability,
                "family": None,
                "phenomena": [],
                "resource_types": [],
                "context_type": None,
                "time_mode": None,
                "requirements": {},
                "event_filter": {},
                "profile_id": None,
                "profile_revision": None,
            },
            "context": None,
            "policy": {},
            "profile": None,
            "candidates": [],
            "coverage": [],
            "decision": {
                "status": "in_progress",
                "code": None,
                "selected_provider": None,
                "selected_capability": None,
                "selected_index": None,
                "fallback_count": 0,
                "reason_code": None,
            },
            "resource": None,
            "timeline": None,
            "freshness": None,
            "network": {
                "instrumentation": "declared_targets_only",
                "declared_targets": [],
                "observed_call_count": None,
            },
            "cache": {
                "instrumentation": "provider_reported_only",
                "entries": [],
            },
            "performance": {
                "total_ms": None,
                "stages_ms": {},
                "providers_checked": 0,
                "providers_contacted": 0,
                "network_calls": None,
            },
            "errors": [],
        }

    def set_request(
        self,
        *,
        family: str | None = None,
        phenomena: list[str] | None = None,
        resource_types: list[str] | None = None,
        context_type: str | None = None,
        time_mode: str | None = None,
        requirements: dict[str, Any] | None = None,
        event_filter: dict[str, Any] | None = None,
        profile_id: str | None = None,
        profile_revision: int | None = None,
    ) -> None:
        request = self.data["request"]
        if family is not None:
            request["family"] = family
        if phenomena is not None:
            request["phenomena"] = list(phenomena)
        if resource_types is not None:
            request["resource_types"] = list(resource_types)
        if context_type is not None:
            request["context_type"] = context_type
        if time_mode is not None:
            request["time_mode"] = time_mode
        if requirements is not None:
            request["requirements"] = deepcopy(requirements)
        if event_filter is not None:
            request["event_filter"] = deepcopy(event_filter)
        if profile_id is not None:
            request["profile_id"] = profile_id
        if profile_revision is not None:
            request["profile_revision"] = profile_revision

    def set_context(self, context: dict[str, Any]) -> None:
        self.data["context"] = diagnostic_value(context)

    def set_policy(self, policy: dict[str, Any]) -> None:
        self.data["policy"] = diagnostic_value(policy)

    def set_profile(self, profile: dict[str, Any] | None) -> None:
        self.data["profile"] = diagnostic_value(profile)

    def _candidate(self, key: str) -> dict[str, Any]:
        for item in self.data["candidates"]:
            if item.get("key") == key:
                return item
        item = {
            "key": key,
            "provider_id": None,
            "provider_name": None,
            "candidate_scope": "standard_core",
            "extension_id": None,
            "capability_id": None,
            "resource_type": None,
            "source_class": None,
            "intent": None,
            "topics": [],
            "data_origin": None,
            "measurement_method": None,
            "observation_kind": None,
            "quantity": None,
            "unit": None,
            "time_semantics": None,
            "coverage_semantics": None,
            "freshness": None,
            "routing_score": None,
            "order": len(self.data["candidates"]),
            "checks": {},
            "coverage": None,
            "attempted": False,
            "provider_contacted": False,
            "duration_ms": None,
            "result": "pending",
            "reason": None,
        }
        self.data["candidates"].append(item)
        return item

    def add_candidate(
        self,
        *,
        key: str,
        provider_id: str,
        provider_name: str,
        capability_id: str,
        resource_type: str,
        source_class: str,
        order: int,
        candidate_scope: str = "standard_core",
        extension_id: str | None = None,
        network_targets: list[dict[str, Any]] | None = None,
        intent: str | None = None,
        topics: list[str] | None = None,
        data_origin: str | None = None,
        measurement_method: str | None = None,
        observation_kind: str | None = None,
        quantity: str | None = None,
        unit: str | None = None,
        time_semantics: dict[str, Any] | None = None,
        coverage_semantics: dict[str, Any] | None = None,
        routing_score: list[int] | None = None,
    ) -> None:
        if candidate_scope not in {"standard_core", "extension"}:
            raise ValueError("candidate_scope must be standard_core or extension")
        if candidate_scope == "extension":
            if not isinstance(extension_id, str) or not extension_id:
                raise ValueError("extension candidate requires extension_id")
        else:
            extension_id = None

        item = self._candidate(key)
        item.update(
            {
                "provider_id": provider_id,
                "provider_name": provider_name,
                "candidate_scope": candidate_scope,
                "extension_id": extension_id,
                "capability_id": capability_id,
                "resource_type": resource_type,
                "source_class": source_class,
                "intent": intent,
                "topics": list(topics or ()),
                "data_origin": data_origin,
                "measurement_method": measurement_method,
                "observation_kind": observation_kind,
                "quantity": quantity,
                "unit": unit,
                "time_semantics": diagnostic_value(time_semantics),
                "coverage_semantics": diagnostic_value(coverage_semantics),
                "routing_score": routing_score,
                "order": order,
            }
        )
        for target in network_targets or []:
            safe = diagnostic_value(target)
            signature = json.dumps(safe, sort_keys=True, ensure_ascii=False)
            existing = {
                json.dumps(row, sort_keys=True, ensure_ascii=False)
                for row in self.data["network"]["declared_targets"]
            }
            if signature not in existing:
                self.data["network"]["declared_targets"].append(safe)

    def candidate_check(
        self,
        key: str,
        check: str,
        passed: bool,
        reason: str | None = None,
    ) -> None:
        self._candidate(key)["checks"][check] = {
            "passed": bool(passed),
            "reason": reason,
        }

    def candidate_attempt(self, key: str) -> None:
        item = self._candidate(key)
        item["attempted"] = True

    def candidate_provider_contact(self, key: str) -> None:
        """Record the first real provider method call for one candidate."""
        item = self._candidate(key)
        if item.get("provider_contacted"):
            return
        item["provider_contacted"] = True
        self.data["performance"]["providers_contacted"] += 1

    def candidate_freshness(self, key: str, freshness: dict[str, Any]) -> None:
        """Attach candidate-specific freshness as soon as provider data time is known."""
        self._candidate(key)["freshness"] = diagnostic_value(freshness)

    def candidate_coverage(self, key: str, coverage: dict[str, Any]) -> None:
        safe = diagnostic_value(coverage)
        item = self._candidate(key)
        item["coverage"] = safe
        self.data["coverage"].append(
            {
                "candidate": key,
                **(safe if isinstance(safe, dict) else {"data": safe}),
            }
        )
        cache = coverage.get("cache") if isinstance(coverage, dict) else None
        if isinstance(cache, dict):
            self.data["cache"]["entries"].append(
                {
                    "candidate": key,
                    **diagnostic_value(cache),
                }
            )

    def candidate_result(
        self,
        key: str,
        *,
        result: str,
        reason: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        item = self._candidate(key)
        item["result"] = result
        item["reason"] = reason
        item["duration_ms"] = duration_ms

    def recorded_fallback_count(self) -> int:
        """Count failed provider attempts, not excluded or unimplemented slots."""
        return sum(
            1
            for item in self.data["candidates"]
            if item.get("attempted") and item.get("result") != "selected"
        )

    def set_decision(
        self,
        *,
        status: str,
        code: str | None = None,
        selected_provider: str | None = None,
        selected_capability: str | None = None,
        selected_index: int | None = None,
        fallback_count: int = 0,
        reason_code: str | None = None,
    ) -> None:
        self.data["decision"].update(
            {
                "status": status,
                "code": code,
                "selected_provider": selected_provider,
                "selected_capability": selected_capability,
                "selected_index": selected_index,
                "fallback_count": fallback_count,
                "reason_code": reason_code,
            }
        )

    def set_resource(
        self,
        resource_type: str,
        payload: dict[str, Any],
        provider_result: dict[str, Any] | None = None,
    ) -> None:
        summary = resource_summary(resource_type, payload, provider_result)
        self.data["resource"] = summary
        self.data["timeline"] = (
            summary.get("timeline")
            if isinstance(summary, dict)
            else None
        )

    def set_freshness(self, freshness: dict[str, Any]) -> None:
        self.data["freshness"] = diagnostic_value(freshness)

    def add_error(
        self,
        *,
        stage: str,
        code: str | None,
        message: str,
        exception_type: str | None = None,
    ) -> None:
        self.data["errors"].append(
            {
                "stage": stage,
                "code": code,
                "message": redact_text(message),
                "exception_type": exception_type,
            }
        )

    def stage_start(self, name: str) -> None:
        self._stage_started[name] = monotonic()

    def stage_end(self, name: str) -> float | None:
        started = self._stage_started.pop(name, None)
        if started is None:
            return None
        duration = round((monotonic() - started) * 1000, 3)
        self.data["performance"]["stages_ms"][name] = duration
        return duration

    def set_providers_checked(self, count: int) -> None:
        self.data["performance"]["providers_checked"] = max(0, int(count))

    def finish(
        self,
        *,
        status: str | None = None,
        code: str | None = None,
    ) -> dict[str, Any]:
        if status is not None:
            self.data["decision"]["status"] = status
        if code is not None:
            self.data["decision"]["code"] = code
        completed_at = utc_now()
        duration = round((monotonic() - self._started) * 1000, 3)
        self.data["meta"]["completed_at"] = completed_at
        self.data["meta"]["duration_ms"] = duration
        self.data["performance"]["total_ms"] = duration
        return diagnostic_value(self.data)
