"""Authenticated provider-neutral V2 synoptic weather geometries.

Separate centres and isobars are intentionally independent: provenance and model
times stay explicit; no implicit combining of unrelated model forecasts.
"""
from __future__ import annotations

import asyncio
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .consumer_profiles import profile_allows_capability, profile_allows_candidate, profile_allows_provider
from .synoptic_eccc import CAPABILITY as CENTERS_CAPABILITY, SynopticUnavailable
from .synoptic_gfs import CAPABILITY as ISOBARS_CAPABILITY, PressureUnavailable
from .wind_field_source import plan_subset, WindFieldUnavailable
from .spatial_coverage import bbox_overlaps, normalize_bbox, point_in_bbox

from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs
import math


def _valid_synoptic_frame(frame, capability):
    """A bounded independent gate between provider and Consumer V2 clients."""
    if not isinstance(frame, dict) or frame.get("capability") != capability:
        return False
    if frame.get("unit") != "hPa" or not isinstance(frame.get("provenance"), dict):
        return False
    provenance = frame["provenance"]
    if not isinstance(provenance.get("provider_id"), str) or not provenance["provider_id"]:
        return False
    if not isinstance(frame.get("coverage"), dict) or frame["coverage"].get("crs") != "EPSG:4326":
        return False
    try:
        run = datetime.fromisoformat(frame["model_run"].replace("Z", "+00:00"))
        valid = datetime.fromisoformat(frame["valid_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(frame["valid_until"].replace("Z", "+00:00"))
        if any(value.tzinfo is None for value in (run, valid, expires)):
            return False
        if run > valid or expires <= valid or expires <= datetime.now(timezone.utc):
            return False
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
    geometry = frame.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "FeatureCollection":
        return False
    features = geometry.get("features")
    if not isinstance(features, list) or len(features) > 20000:
        return False
    for item in features:
        if not isinstance(item, dict) or item.get("type") != "Feature":
            return False
        geom, props = item.get("geometry"), item.get("properties")
        if not isinstance(geom, dict) or not isinstance(props, dict):
            return False
        pressure = props.get("pressure_hpa")
        if type(pressure) not in (int, float) or not math.isfinite(pressure) or not 870 <= pressure <= 1090:
            return False
        if capability == CENTERS_CAPABILITY:
            p = geom.get("coordinates")
            if (geom.get("type") != "Point" or props.get("kind") not in ("H", "L")
                    or not isinstance(p, list) or len(p) != 2
                    or any(type(x) not in (int, float) or not math.isfinite(x) for x in p)
                    or not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90):
                return False
        else:
            if geom.get("type") not in ("LineString", "MultiLineString"):
                return False
            paths = [geom.get("coordinates")] if geom["type"] == "LineString" else geom.get("coordinates")
            if not isinstance(paths, list) or len(paths) > 20000:
                return False
            for path in paths:
                if not isinstance(path, list) or len(path) < 2 or len(path) > 20000:
                    return False
                for p in path:
                    if (not isinstance(p, list) or len(p) != 2
                            or any(type(x) not in (int, float) or not math.isfinite(x) for x in p)
                            or not -540 <= p[0] <= 540 or not -90 <= p[1] <= 90):
                        return False
    return True



FRONTS_CAPABILITY = "weather.synoptic.fronts"
RASTER_CAPABILITY = "weather.synoptic.pressure_raster"
SOURCE_CAPABILITY = "weather.synoptic.pressure_source"


def _valid_synoptic_fronts(frame):
    """Fail closed on unknown front classes, geometry, coverage and authority."""
    if not isinstance(frame, dict) or frame.get("capability") != FRONTS_CAPABILITY:
        return False
    if frame.get("unit") != "feature" or not isinstance(frame.get("provenance"), dict):
        return False
    provenance = frame["provenance"]
    if not isinstance(provenance.get("provider_id"), str) or provenance.get("data_origin") != "human_analysis":
        return False
    coverage = frame.get("coverage")
    bbox = normalize_bbox(coverage)
    if bbox is None or coverage.get("crs") != "EPSG:4326" or coverage.get("type") != "bbox":
        return False
    try:
        run = datetime.fromisoformat(frame["model_run"].replace("Z", "+00:00"))
        valid = datetime.fromisoformat(frame["valid_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(frame["valid_until"].replace("Z", "+00:00"))
        if any(t.tzinfo is None for t in (run, valid, expires)):
            return False
        if run > valid or expires <= valid or expires <= datetime.now(timezone.utc):
            return False
    except (ValueError, KeyError, AttributeError, TypeError):
        return False
    geometry = frame.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "FeatureCollection":
        return False
    features = geometry.get("features")
    if not isinstance(features, list) or len(features) > 160:
        return False
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            return False
        geo, properties = feature.get("geometry"), feature.get("properties")
        if not isinstance(geo, dict) or not isinstance(properties, dict):
            return False
        if properties.get("front_type") not in ("cold", "warm", "occluded", "stationary"):
            return False
        side = properties.get("symbol_side")
        if properties.get("symbol_side_authorized") is True:
            if side not in ("left", "right"):
                return False
        elif properties.get("symbol_side_authorized") is not False or side is not None:
            return False
        points = geo.get("coordinates")
        if geo.get("type") != "LineString" or not isinstance(points, list) or not 2 <= len(points) <= 240:
            return False
        for point in points:
            if (not isinstance(point, list) or len(point) != 2
                    or any(type(v) not in (float, int) or not math.isfinite(v) for v in point)
                    or not point_in_bbox(point[1], point[0], bbox)):
                return False
    return True


def _valid_synoptic_resource(frame, capability):
    """Fail-closed V2 validation of an image/file descriptor, never a vector."""
    if not isinstance(frame, dict) or frame.get("capability") != capability:
        return False
    if not isinstance(frame.get("provenance"), dict) or not isinstance(
            frame["provenance"].get("provider_id"), str):
        return False
    coverage = frame.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("crs") != "EPSG:4326":
        return False
    try:
        valid = datetime.fromisoformat(frame["valid_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(frame["valid_until"].replace("Z", "+00:00"))
        if valid.tzinfo is None or expires.tzinfo is None or expires <= valid or expires <= datetime.now(timezone.utc):
            return False
        run_raw = frame.get("model_run")
        # A model-derived ready resource needs a source-proven run time.
        # None is not proof and must not bypass the required ordering.
        if not isinstance(run_raw, str):
            return False
        run = datetime.fromisoformat(run_raw.replace("Z", "+00:00"))
        if run.tzinfo is None or run > valid:
            return False
    except (KeyError, ValueError, TypeError, AttributeError):
        return False
    if capability == RASTER_CAPABILITY:
        if frame.get("unit") != "hPa" or coverage.get("type") != "bbox":
            return False
        for key, lower, upper in (("west", -180, 180), ("east", -180, 180),
                                  ("south", -90, 90), ("north", -90, 90)):
            value = coverage.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
                return False
        if coverage["south"] >= coverage["north"]:
            return False
        raster = frame.get("raster")
        if not isinstance(raster, dict) or raster.get("type") != "wms_raster_tile":
            return False
        if raster.get("layer") not in ("Icon-eu_reg00625_fd_sl_QFF", "dwd:Icon-eu_reg00625_fd_sl_QFF") or raster.get("tile_size") != 256:
            return False
        url = raster.get("tile_url")
        if not isinstance(url, str):
            return False
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc not in (
                "maps.dwd.de", "brz-maps.dwd.de") or parsed.path not in (
                "/geoserver/ows", "/geoserver/dwd/wms"):
            return False
        query = parse_qs(parsed.query)
        return (
            query.get("request", [None])[0] == "GetMap"
            and query.get("layers", [None])[0] == raster["layer"]
            and query.get("format", [None])[0] == "image/png"
            and "{bbox-epsg-3857}" in parsed.query
        )
    if capability == SOURCE_CAPABILITY:
        if frame.get("unit") != "Pa" or coverage.get("type") != "global":
            return False
        data = frame.get("data_file")
        if not isinstance(data, dict) or data.get("format") != "GRIB2":
            return False
        if (data.get("parameter") != "msl" or data.get("level_type") != "sfc"
                or data.get("signature_verified") is not True
                or data.get("decoded") is not False):
            return False
        if (type(data.get("byte_offset")) is not int or data["byte_offset"] < 0
                or type(data.get("byte_length")) is not int
                or not 16 <= data["byte_length"] <= 8_000_000):
            return False
        url = data.get("url")
        if not isinstance(url, str):
            return False
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.netloc == "data.ecmwf.int"
                and parsed.path.startswith("/forecasts/")
                and parsed.path.endswith(".grib2") and not parsed.query)
    return False


CAPABILITIES = frozenset((
    CENTERS_CAPABILITY, ISOBARS_CAPABILITY, FRONTS_CAPABILITY,
    RASTER_CAPABILITY, SOURCE_CAPABILITY
))
META = {
    cap: {"family": "synoptic", "phenomena": ["front"] if cap == FRONTS_CAPABILITY else ["pressure"],
          "resource_types": [(
              "raster_tile" if cap == RASTER_CAPABILITY else
              "data_file" if cap == SOURCE_CAPABILITY else "vector_geometry"
          )]}
    for cap in CAPABILITIES
}
SEMANTICS = {"data_origin": "model", "observation_kind": "forecast"}
METHODS = {
    CENTERS_CAPABILITY: ("synoptic_centers_info", "async_fetch_synoptic_centers"),
    ISOBARS_CAPABILITY: ("synoptic_isobars_info", "async_fetch_synoptic_isobars"),
    FRONTS_CAPABILITY: ("synoptic_fronts_info", "async_fetch_synoptic_fronts"),
    RASTER_CAPABILITY: ("synoptic_raster_info", "async_fetch_synoptic_raster"),
    SOURCE_CAPABILITY: ("synoptic_pressure_source_info", "async_fetch_synoptic_pressure_source"),
}


async def resolve_synoptic(hass, msg):
    from .consumer_api import _runtime_state, _async_providers, _profile_for_request, _candidate_enabled
    capability = msg.get("capability")
    response = {"schema": "weather_router.consumer.synoptic.v2", "contract_version": 2,
                "capability": capability, "status": "unavailable", "frame": None}
    def unavailable(code, **details):
        return {**response, "unavailable": {"code": code, **details}}
    if msg.get("contract_version") != 2 or capability not in CAPABILITIES:
        return unavailable("synoptic_unsupported_contract")
    if msg.get("time") != {"mode": "latest"}:
        return unavailable("synoptic_unsupported_time")
    context = msg.get("context")
    if not isinstance(context, dict) or set(context) != {"bbox"}:
        return unavailable("synoptic_invalid_context")
    bbox = context["bbox"]
    try:
        plan_subset(bbox)
    except WindFieldUnavailable:
        return unavailable("synoptic_invalid_bbox")
    if capability == FRONTS_CAPABILITY:
        span = bbox["east"] - bbox["west"]
        if span >= 360:
            bbox = {**bbox, "west": -180., "east": 180.}
        else:
            west = (bbox["west"] + 180) % 360 - 180
            east = west + span % 360
            bbox = {**bbox, "west": west, "east": east if east <= 180 else east - 360}
    ready, state = _runtime_state(hass)
    if not ready:
        return unavailable("router_not_ready")
    if not state["router_enabled"]:
        return unavailable("router_disabled")
    if "weather" not in state["enabled_domains"]:
        return unavailable("domain_disabled")
    try:
        _, profile = _profile_for_request(hass, msg)
    except Exception as error:
        return unavailable(getattr(error, "code", "profile_not_available"))
    allowed, reason = profile_allows_capability(
        profile, {"public_capabilities": {capability: META[capability]}}, capability)
    if not allowed:
        return unavailable(reason)
    allowed, reason = profile_allows_candidate(profile, SEMANTICS)
    if not allowed:
        return unavailable(reason)
    providers = await _async_providers(hass)
    rejections = []
    # One request has a finite global budget, not 7x a full source timeout.
    # This bounds the multi-provider outage experience and HA WS workload.
    deadline = asyncio.get_running_loop().time() + 75.0
    info_method, fetch_method = METHODS[capability]
    # Prefer authoritative precomputed geometries over derived model extrema.
    # For derived grids, WR uses a provider-declared priority without tying the
    # public Consumer contract to vendor names or order of package imports.
    # Ranking uses declared data class, never a hard-coded provider identity.
    candidate_order = []
    for provider in providers.values():
        info = getattr(provider, info_method, None)
        if callable(info):
            try:
                properties = info()
                if isinstance(properties, dict) and properties.get("capability") == capability:
                    declared_priority = properties.get("synoptic_priority", 40)
                    if type(declared_priority) is not int or not 1 <= declared_priority <= 100:
                        declared_priority = 40
                    candidate_order.append((
                        0 if properties.get("data_kind") == "precomputed_vector" else 1,
                        declared_priority,
                        len(candidate_order), provider))
            except Exception:
                rejections.append({"provider_id": provider.id, "code": "synoptic_provider_info_invalid"})
    candidate_order.sort(key=lambda item: (item[0], item[1], item[2]))
    for _, _, _, provider in candidate_order:
        info = getattr(provider, info_method, None)
        fetch = getattr(provider, fetch_method, None)
        if not callable(info) or not callable(fetch):
            continue
        try:
            declared = info()
        except Exception:
            rejections.append({"provider_id": provider.id, "code": "synoptic_provider_info_invalid"})
            continue
        if not isinstance(declared, dict) or declared.get("capability") != capability:
            continue
        eligible, reason = _candidate_enabled(state, provider, capability)
        if not eligible or not profile_allows_provider(profile, provider.id):
            rejections.append({"provider_id": provider.id, "code": reason or "profile_provider_filtered"})
            continue
        if capability == FRONTS_CAPABILITY:
            provider_bbox = normalize_bbox(declared.get("coverage_bbox"))
            if provider_bbox is not None and not bbox_overlaps(provider_bbox, bbox):
                rejections.append({"provider_id": provider.id, "code": "synoptic_fronts_no_coverage"})
                continue
        try:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0.5:
                return unavailable("synoptic_request_budget_exceeded",
                                   sources=rejections)
            # A regional service cannot consume the entire global
            # failover budget. Reserve time for a genuinely global fallback.
            # Providers declare coverage; clients never choose the order.
            source_budget = (
                12.5 if declared.get("coverage") == "regional"
                else 32.0
            )
            async with asyncio.timeout(min(source_budget, remaining)):
                frame = await fetch(hass, bbox)
            # A provider switched off during the download cannot still deliver.
            current_ready, current = _runtime_state(hass)
            _, current_profile = _profile_for_request(hass, msg)
            permitted = (
                current_ready
                and _candidate_enabled(current, provider, capability)[0]
                and profile_allows_provider(current_profile, provider.id)
                and profile_allows_capability(
                    current_profile, {"public_capabilities": {capability: META[capability]}},
                    capability)[0]
                and profile_allows_candidate(current_profile, SEMANTICS)[0])
            if not permitted:
                return unavailable("synoptic_policy_changed")
            # Reject malformed or expired data before it can become a displayed
            # synoptic frame. A bad candidate is a reason to try the next eligible
            # provider, not to abort the entire provider-independent resolution.
            valid_frame = (
                _valid_synoptic_resource(frame, capability)
                if capability in (RASTER_CAPABILITY, SOURCE_CAPABILITY)
                else _valid_synoptic_fronts(frame)
                if capability == FRONTS_CAPABILITY
                else _valid_synoptic_frame(frame, capability)
            )
            if not valid_frame:
                rejections.append({"provider_id": provider.id,
                                   "code": "synoptic_invalid_provider_frame"})
                continue
            if frame["provenance"]["provider_id"] != provider.id:
                rejections.append({"provider_id": provider.id,
                                   "code": "synoptic_provider_provenance_mismatch"})
                continue
            # Source semantics may be more specific than the candidate's
            # default model declaration: NOAA WPC is human surface analysis,
            # whereas NOAA GFS is numeric model forecast. Never let a
            # profile-excluded final source slip through after the download.
            origin = frame["provenance"].get("data_origin")
            method = frame["provenance"].get("measurement_method")
            if not isinstance(origin, str) or not isinstance(method, str):
                rejections.append({"provider_id": provider.id,
                                   "code": "synoptic_source_semantics_missing"})
                continue
            actual_semantics = {
                **SEMANTICS,
                "data_origin": origin,
                "measurement_method": method,
                "observation_kind": (
                    "observation" if origin == "human_analysis" else
                    SEMANTICS["observation_kind"]
                ),
            }
            actual_allowed, actual_reason = profile_allows_candidate(
                current_profile, actual_semantics)
            if not actual_allowed:
                rejections.append({"provider_id": provider.id,
                                   "code": actual_reason})
                continue
            return {**response, "status": "ready", "frame": frame}
        except (SynopticUnavailable, PressureUnavailable, TimeoutError, ValueError) as error:
            code = "synoptic_timeout" if isinstance(error, TimeoutError) else str(error)
            if not code.startswith("synoptic_"):
                code = "synoptic_source_unavailable"
            rejections.append({"provider_id": provider.id, "code": code})
    return unavailable(rejections[-1]["code"] if rejections else "synoptic_no_eligible_provider",
                       sources=rejections)


@websocket_api.websocket_command({
    vol.Required("type"): "weather_router/consumer/resolve_synoptic",
    vol.Required("contract_version"): int,
    vol.Required("capability"): str,
    vol.Required("context"): dict,
    vol.Required("time"): dict,
    vol.Optional("profile_id"): str,
    vol.Optional("consumer_id"): str,
})
@websocket_api.async_response
async def websocket_resolve_synoptic(hass: HomeAssistant, connection, msg):
    from .diagnostic_center import record
    try:
        answer = await resolve_synoptic(hass, msg)
    except Exception:
        answer = {"schema": "weather_router.consumer.synoptic.v2", "contract_version": 2,
                  "capability": msg.get("capability"), "status": "unavailable", "frame": None,
                  "unavailable": {"code": "synoptic_unavailable"}}
    frame = answer.get("frame") or {}
    record(hass, category="consumer",
           outcome="success" if answer["status"] == "ready" else "unavailable",
           details={"capability": answer["capability"],
                    "code": answer.get("unavailable", {}).get("code"),
                    "features": len(frame.get("geometry", {}).get("features", [])),
                    "model": frame.get("model")})
    connection.send_result(msg["id"], answer)


def async_register(hass: HomeAssistant):
    websocket_api.async_register_command(hass, websocket_resolve_synoptic)
