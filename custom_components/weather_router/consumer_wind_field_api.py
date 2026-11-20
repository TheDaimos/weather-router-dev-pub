"""Additive, authenticated Consumer V2 numeric windfield resolution.

No modifications to V1 inventory, raster resolution or precipitation routing.
Registered provider extensions advertise their own optional windfield support.
"""
from __future__ import annotations

import asyncio
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .consumer_profiles import profile_allows_capability, profile_allows_candidate, profile_allows_provider
from .wind_field_source import CAPABILITY, WindFieldUnavailable, plan_subset

METADATA = {"family": "field", "phenomena": ["wind"], "resource_types": ["vector_grid"]}
SEMANTICS = {"data_origin": "model", "measurement_method": "nwp_model_data_file", "observation_kind": "forecast"}


async def resolve_wind_field(hass, msg):
    from .consumer_api import _runtime_state, _async_providers, _profile_for_request, _candidate_enabled
    response = {"schema": "weather_router.consumer.wind_field.v2", "contract_version": 2,
                "capability": CAPABILITY, "status": "unavailable", "frame": None}
    def unavailable(code, **details):
        return {**response, "unavailable": {"code": code, **details}}
    if msg.get("contract_version") != 2 or msg.get("capability") != CAPABILITY:
        return unavailable("wind_unsupported_contract")
    if msg.get("time") != {"mode": "latest"}:
        return unavailable("wind_unsupported_time")
    context = msg.get("context", {})
    if not isinstance(context, dict) or set(context) != {"bbox"}:
        return unavailable("wind_invalid_context")
    try:
        plan_subset(context["bbox"])
    except WindFieldUnavailable as error:
        return unavailable(str(error))
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
    allowed, reason = profile_allows_capability(profile, {"public_capabilities": {CAPABILITY: METADATA}}, CAPABILITY)
    if not allowed:
        return unavailable(reason)
    allowed, reason = profile_allows_candidate(profile, SEMANTICS)
    if not allowed:
        return unavailable(reason)
    providers = await _async_providers(hass)
    rejections = []
    # Provider catalog order remains core-owned; a consumer cannot name or enable a source.
    for provider in providers.values():
        info = getattr(provider, "wind_field_info", None)
        fetch = getattr(provider, "async_fetch_wind_field", None)
        if not callable(info) or not callable(fetch) or info().get("capability") != CAPABILITY:
            continue
        eligible, reason = _candidate_enabled(state, provider, CAPABILITY)
        if not eligible or not profile_allows_provider(profile, provider.id):
            rejections.append({"provider_id": provider.id, "code": reason or "profile_provider_filtered"})
            continue
        try:
            async with asyncio.timeout(32):
                frame = await fetch(hass, context["bbox"])
            # Global settings can change while the subset is in flight: fail closed.
            current_ready, current = _runtime_state(hass)
            _, current_profile = _profile_for_request(hass, msg)
            if not current_ready or not _candidate_enabled(current, provider, CAPABILITY)[0] or not profile_allows_provider(current_profile, provider.id) or not profile_allows_capability(current_profile, {"public_capabilities": {CAPABILITY: METADATA}}, CAPABILITY)[0] or not profile_allows_candidate(current_profile, SEMANTICS)[0]:
                return unavailable("wind_policy_changed")
            return {**response, "status": "ready", "frame": frame}
        except (WindFieldUnavailable, TimeoutError) as error:
            rejections.append({"provider_id": provider.id, "code": str(error) if isinstance(error, WindFieldUnavailable) else "wind_source_timeout"})
    return unavailable(rejections[-1]["code"] if rejections else "wind_field_not_supported", sources=rejections)


@websocket_api.websocket_command({
    vol.Required("type"): "weather_router/consumer/resolve_wind_field",
    vol.Required("contract_version"): int, vol.Required("capability"): str,
    vol.Required("context"): dict, vol.Required("time"): dict,
    vol.Optional("profile_id"): str, vol.Optional("consumer_id"): str,
})
@websocket_api.async_response
async def websocket_resolve_wind_field(hass: HomeAssistant, connection, msg):
    """HA WebSocket authentication supplies access; no public raster URL/token."""
    from .diagnostic_center import record
    try:
        response = await resolve_wind_field(hass, msg)
    except Exception:
        response = {"schema": "weather_router.consumer.wind_field.v2", "contract_version": 2,
                    "capability": CAPABILITY, "status": "unavailable", "frame": None,
                    "unavailable": {"code": "wind_field_unavailable"}}
    record(hass, category="consumer", outcome="success" if response["status"] == "ready" else "unavailable",
           details={"capability": CAPABILITY, "code": response.get("unavailable", {}).get("code"),
                    "nodes": len((response.get("frame") or {}).get("grid", {}).get("valid_mask", []))})
    connection.send_result(msg["id"], response)


def async_register(hass: HomeAssistant):
    websocket_api.async_register_command(hass, websocket_resolve_wind_field)
