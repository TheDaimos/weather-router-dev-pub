"""WeatherRouter WebSocket API used by the internal diagnostic lab."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
import json
from time import monotonic
import traceback
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_CONTRACT_VERSION,
    CONF_ENABLED_DOMAINS,
    CONF_ENABLED_PROVIDERS,
    CONF_CONSUMER_PROFILES,
    CONF_LOG_GIT_BRANCH,
    CONF_LOG_GIT_TOKEN,
    CONF_ROUTER_ENABLED,
    DOMAIN,
    LOG_GIT_REPOSITORY,
    LOG_GIT_ROOT,
    ROUTER_DOMAINS,
    ROUTER_TOPIC_GROUPS,
    ROUTER_TOPICS,
)
from .consumer_profiles import normalize_consumer_profile
from .log_git_export import WeatherRouterLogExportError, WeatherRouterLogGitClient
from .providers import provider_catalog
from .routing_diagnostic_core import (
    ROUTING_DIAGNOSTIC_SCHEMA,
    diagnostic_value as _diagnostic_value,
    redact_text as _redact_text,
)
from .routing_diagnostics import provider_runtime_summary


def _exception_report(err: BaseException) -> dict[str, Any]:
    """Return a redacted machine-readable exception including traceback and cause chain."""
    chain: list[dict[str, str]] = []
    seen: set[int] = set()
    current: BaseException | None = err
    while current is not None and id(current) not in seen and len(chain) < 12:
        seen.add(id(current))
        chain.append(
            {
                "type": type(current).__name__,
                "module": type(current).__module__,
                "message": _redact_text(str(current)),
            }
        )
        current = current.__cause__ or current.__context__

    formatted = traceback.TracebackException.from_exception(
        err,
        capture_locals=False,
    ).format()
    return {
        "type": type(err).__name__,
        "module": type(err).__module__,
        "message": _redact_text(str(err)),
        "chain": chain,
        "traceback": [_redact_text(line.rstrip("\n")) for line in formatted],
    }


def _coordinate(value: Any, minimum: float, maximum: float) -> float:
    """Validate one coordinate from a WebSocket request."""
    if isinstance(value, bool):
        raise vol.Invalid("invalid coordinate")
    coordinate = float(value)
    if not isfinite(coordinate) or not minimum <= coordinate <= maximum:
        raise vol.Invalid("invalid coordinate")
    return coordinate


def _capability_info(capability: Any) -> dict[str, Any]:
    """Serialize one capability including optional explanatory metadata."""
    return {
        "id": capability.id,
        "name": capability.name,
        "unit": capability.unit,
        "source_class": capability.source_class,
        "render_mode": capability.render_mode,
        "description": getattr(capability, "description", None),
        "coverage": getattr(capability, "coverage", None),
        "temporal_resolution": getattr(capability, "temporal_resolution", None),
        "typical_latency": getattr(capability, "typical_latency", None),
        "strengths": list(getattr(capability, "strengths", ()) or ()),
        "limitations": list(getattr(capability, "limitations", ()) or ()),
        "documentation_url": getattr(capability, "documentation_url", None),
    }


def _provider_info(provider: Any) -> dict[str, Any]:
    """Serialize optional structured provider help with a safe generic fallback."""
    get_info = getattr(provider, "provider_info", None)
    if callable(get_info):
        info = get_info()
        return {
            "summary": info.summary,
            "coverage": info.coverage,
            "strengths": list(info.strengths),
            "limitations": list(info.limitations),
            "documentation_url": info.documentation_url,
            "attribution": info.attribution,
            "services": [dict(item) for item in info.services],
        }

    return {
        "summary": f"{provider.name} stellt WeatherRouter-Daten über den gemeinsamen Providervertrag bereit.",
        "coverage": None,
        "strengths": [],
        "limitations": [],
        "documentation_url": None,
        "attribution": None,
        "services": [],
    }


def _network_targets(provider: Any) -> list[dict[str, Any]]:
    """Serialize one provider's secret-free network metadata."""
    get_targets = getattr(provider, "network_targets", None)
    if not callable(get_targets):
        return []

    result: list[dict[str, Any]] = []
    for target in get_targets():
        result.append(
            {
                "purpose": target.purpose,
                "scheme": target.scheme,
                "host": target.host,
                "port": target.port,
                "target_type": target.target_type,
                "required": target.required,
                "capabilities": list(target.capabilities),
                "note": target.note,
            }
        )
    return result


def _weather_router_entry(hass: HomeAssistant):
    """Return the single configured WeatherRouter entry."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise WeatherRouterLogExportError("WeatherRouter is not configured")
    return entries[0]


async def _async_provider_catalog(hass: HomeAssistant) -> dict[str, Any]:
    """Load only currently visible providers outside Home Assistant's event loop."""
    return await hass.async_add_executor_job(provider_catalog)


async def _async_all_provider_catalog(hass: HomeAssistant) -> dict[str, Any]:
    """Load visible plus hidden providers for persisted-option validation only."""
    return await hass.async_add_executor_job(
        lambda: provider_catalog(include_hidden=True)
    )


def _routing_settings(hass: HomeAssistant) -> dict[str, Any]:
    """Return current persistent router eligibility settings."""
    entry = _weather_router_entry(hass)
    runtime = getattr(entry, "runtime_data", None)
    resolver = getattr(runtime, "routing_settings", None)
    if callable(resolver):
        settings = resolver()
        return {
            "router_enabled": bool(settings["router_enabled"]),
            "enabled_domains": set(settings["enabled_domains"]),
            "enabled_providers": set(settings["enabled_providers"]),
        }
    return {
        "router_enabled": bool(entry.options.get(CONF_ROUTER_ENABLED, True)),
        "enabled_domains": set(entry.options.get(CONF_ENABLED_DOMAINS, ())),
        "enabled_providers": set(entry.options.get(CONF_ENABLED_PROVIDERS, ())),
    }


def _capability_domain(provider: Any, capability: Any) -> str:
    """Resolve the functional router domain for one capability."""
    provider_id = str(getattr(provider, "id", ""))
    domains = tuple(getattr(provider, "router_domains", ("weather",)))

    if provider_id == "bbk_mowas":
        return "civil_protection"
    if provider_id == "bbk_police":
        return "security"
    if provider_id == "aviation_weather":
        return "aviation"
    if provider_id in {"noaa_swpc", "nasa_iss", "nasa_moon"}:
        return "space"
    if getattr(capability, "render_mode", None) == "hazard_feed":
        if "natural_hazards" in domains:
            return "natural_hazards"
        if domains:
            return domains[0]
    if "weather" in domains:
        return "weather"
    return domains[0] if domains else "weather"


def _provider_policy(
    settings: dict[str, Any],
    provider: Any,
) -> tuple[bool, str | None]:
    """Return whether a provider can participate in router work at all."""
    if not settings["router_enabled"]:
        return False, "router_disabled"
    if provider.id not in settings["enabled_providers"]:
        return False, "provider_disabled"
    domains = set(getattr(provider, "router_domains", ("weather",)))
    if domains and not domains.intersection(settings["enabled_domains"]):
        return False, "domain_disabled"
    return True, None


def _capability_policy(
    settings: dict[str, Any],
    provider: Any,
    capability: Any,
) -> tuple[bool, str | None]:
    """Return hard eligibility for one provider capability."""
    provider_ok, provider_reason = _provider_policy(settings, provider)
    if not provider_ok:
        return False, provider_reason
    domain = _capability_domain(provider, capability)
    if domain not in settings["enabled_domains"]:
        return False, "domain_disabled"
    return True, None


def _catalog_provider_row(
    settings: dict[str, Any],
    provider: Any,
) -> dict[str, Any]:
    """Serialize one provider with router eligibility on provider and capability level."""
    provider_eligible, provider_reason = _provider_policy(settings, provider)
    capabilities: list[dict[str, Any]] = []
    for capability in provider.capabilities():
        eligible, reason = _capability_policy(settings, provider, capability)
        capabilities.append(
            {
                **_capability_info(capability),
                "router_domain": _capability_domain(provider, capability),
                "eligible": eligible,
                "disabled_reason": reason,
            }
        )
    return {
        "id": provider.id,
        "name": provider.name,
        "revision": getattr(provider, "revision", None),
        "router_domains": list(getattr(provider, "router_domains", ("weather",))),
        "topics": [
            topic_id
            for topic_id in getattr(provider, "router_topics", ())
            if topic_id in ROUTER_TOPICS
        ],
        "default_enabled": bool(getattr(provider, "router_default_enabled", True)),
        "enabled_by_user": provider.id in settings["enabled_providers"],
        "eligible": provider_eligible,
        "disabled_reason": provider_reason,
        "capabilities": capabilities,
        "info": _provider_info(provider),
        "network_targets": _network_targets(provider),
    }


def _routing_settings_payload(
    settings: dict[str, Any],
    providers: dict[str, Any],
) -> dict[str, Any]:
    """Serialize routing settings and all provider/domain eligibility."""
    provider_rows = []
    for provider in providers.values():
        eligible, reason = _provider_policy(settings, provider)
        provider_rows.append(
            {
                "id": provider.id,
                "name": provider.name,
                "domains": list(getattr(provider, "router_domains", ("weather",))),
                "display_group": getattr(provider, "router_display_group", None),
                "topics": [
                    topic_id
                    for topic_id in getattr(provider, "router_topics", ())
                    if topic_id in ROUTER_TOPICS
                ],
                "is_extension": bool(getattr(provider, "weather_router_extension_id", None)),
                "default_enabled": bool(getattr(provider, "router_default_enabled", True)),
                "enabled_by_user": provider.id in settings["enabled_providers"],
                "eligible": eligible,
                "disabled_reason": reason,
            }
        )
    return {
        "schema": "weather_router.routing_settings.v1",
        "router_enabled": settings["router_enabled"],
        "domains": [
            {
                "id": domain_id,
                "name": label,
                "enabled": domain_id in settings["enabled_domains"],
            }
            for domain_id, label in ROUTER_DOMAINS.items()
        ],
        "providers": provider_rows,
        "topic_groups": [
            {
                "id": group_id,
                "name": metadata["name"],
                "domain": metadata["domain"],
                "topics": [
                    {"id": topic_id, "name": topic_name}
                    for topic_id, topic_name in metadata["topics"].items()
                ],
            }
            for group_id, metadata in ROUTER_TOPIC_GROUPS.items()
        ],
    }


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "weather_router/routing_settings"}
)
@websocket_api.async_response
async def websocket_routing_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return persistent routing/domain/provider eligibility without network calls."""
    providers = await _async_provider_catalog(hass)
    connection.send_result(
        msg["id"],
        _routing_settings_payload(_routing_settings(hass), providers),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/routing_settings_update",
        vol.Optional("router_enabled"): bool,
        vol.Optional("enabled_domains"): [str],
        vol.Optional("enabled_providers"): [str],
    }
)
@websocket_api.async_response
async def websocket_routing_settings_update(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist router/domain/provider eligibility atomically."""
    providers = await _async_provider_catalog(hass)
    settings = _routing_settings(hass)

    enabled_domains = msg.get("enabled_domains", list(settings["enabled_domains"]))
    unknown_domains = sorted(set(enabled_domains) - set(ROUTER_DOMAINS))
    if unknown_domains:
        connection.send_error(
            msg["id"],
            "invalid_router_domains",
            ",".join(unknown_domains),
        )
        return

    enabled_providers = msg.get(
        "enabled_providers",
        list(settings["enabled_providers"]),
    )
    all_providers = await _async_all_provider_catalog(hass)
    # OPERA is a source-acquisition-only opt-in here; not a V1 catalog route.
    unknown_providers = sorted(set(enabled_providers) - (set(all_providers) | {"opera"}))
    if unknown_providers:
        connection.send_error(
            msg["id"],
            "invalid_router_providers",
            ",".join(unknown_providers),
        )
        return

    entry = _weather_router_entry(hass)
    runtime = getattr(entry, "runtime_data", None)
    setter = getattr(runtime, "async_set_routing", None)
    if not callable(setter):
        connection.send_error(
            msg["id"],
            "routing_settings_unavailable",
            "WeatherRouter runtime data is not ready",
        )
        return

    setter(
        router_enabled=msg.get("router_enabled"),
        enabled_domains=enabled_domains,
        enabled_providers=enabled_providers,
    )
    from .opera_source_monitor import async_apply_opera_provider_selection
    await async_apply_opera_provider_selection(
        hass, enabled_providers=enabled_providers,
        router_enabled=msg.get("router_enabled", settings["router_enabled"]),
        enabled_domains=enabled_domains)

    providers = await _async_provider_catalog(hass)
    connection.send_result(
        msg["id"],
        _routing_settings_payload(_routing_settings(hass), providers),
    )


def _consumer_profiles(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Return persisted Consumer API profiles without provider/network work."""
    entry = _weather_router_entry(hass)
    runtime = getattr(entry, "runtime_data", None)
    resolver = getattr(runtime, "consumer_profiles", None)
    if callable(resolver):
        return resolver()
    raw = entry.options.get(CONF_CONSUMER_PROFILES, {})
    return {
        str(profile_id): dict(profile)
        for profile_id, profile in raw.items()
        if isinstance(profile_id, str) and isinstance(profile, dict)
    }


def _consumer_profiles_payload(hass: HomeAssistant) -> dict[str, Any]:
    """Serialize profiles plus the non-negotiable policy semantics."""
    profiles = _consumer_profiles(hass)
    return {
        "schema": "weather_router.consumer_profiles.v1",
        "policy": {
            "mode": "restrictive_only",
            "provider_rule": "deny_only",
            "provider_priority_supported": False,
            "global_disabled_provider_can_be_reenabled": False,
        },
        "profiles": [
            {"id": profile_id, **profile}
            for profile_id, profile in sorted(profiles.items())
        ],
    }


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "weather_router/consumer_profiles"}
)
@websocket_api.async_response
async def websocket_consumer_profiles(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List persistent Consumer API profiles."""
    connection.send_result(msg["id"], _consumer_profiles_payload(hass))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/consumer_profile_upsert",
        vol.Required("profile"): dict,
    }
)
@websocket_api.async_response
async def websocket_consumer_profile_upsert(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or replace one restrictive Consumer API profile."""
    raw = dict(msg["profile"])
    profile_id = raw.pop("id", None)
    if not isinstance(profile_id, str):
        connection.send_error(
            msg["id"],
            "invalid_consumer_profile",
            "profile.id is required",
        )
        return

    providers = await _async_provider_catalog(hass)
    profiles = _consumer_profiles(hass)
    current = profiles.get(profile_id, {})
    try:
        profile = normalize_consumer_profile(
            profile_id,
            raw,
            current_revision=int(current.get("revision", 0) or 0),
            known_domains=set(ROUTER_DOMAINS),
            known_providers=set(providers),
        )
    except (TypeError, ValueError) as err:
        connection.send_error(msg["id"], "invalid_consumer_profile", str(err))
        return

    profiles[profile_id] = profile
    entry = _weather_router_entry(hass)
    runtime = getattr(entry, "runtime_data", None)
    setter = getattr(runtime, "async_set_consumer_profiles", None)
    if not callable(setter):
        connection.send_error(
            msg["id"],
            "consumer_profiles_unavailable",
            "WeatherRouter runtime data is not ready",
        )
        return
    setter(profiles)
    connection.send_result(msg["id"], _consumer_profiles_payload(hass))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/consumer_profile_delete",
        vol.Required("profile_id"): str,
    }
)
@websocket_api.async_response
async def websocket_consumer_profile_delete(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete one Consumer API profile without changing global routing."""
    profiles = _consumer_profiles(hass)
    profile_id = msg["profile_id"]
    if profile_id not in profiles:
        connection.send_error(msg["id"], "consumer_profile_not_found", profile_id)
        return
    profiles.pop(profile_id)

    entry = _weather_router_entry(hass)
    runtime = getattr(entry, "runtime_data", None)
    setter = getattr(runtime, "async_set_consumer_profiles", None)
    if not callable(setter):
        connection.send_error(
            msg["id"],
            "consumer_profiles_unavailable",
            "WeatherRouter runtime data is not ready",
        )
        return
    setter(profiles)
    connection.send_result(msg["id"], _consumer_profiles_payload(hass))


@websocket_api.websocket_command({vol.Required("type"): "weather_router/providers"})
@websocket_api.async_response
async def websocket_providers(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return providers, capabilities and secret-free network metadata."""
    providers = await _async_provider_catalog(hass)
    settings = _routing_settings(hass)
    connection.send_result(
        msg["id"],
        {
            "api_version": API_CONTRACT_VERSION,
            "router_enabled": settings["router_enabled"],
            "providers": [
                _catalog_provider_row(settings, provider)
                for provider in providers.values()
            ],
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/diagnostic_query",
        vol.Required("latitude"): vol.Coerce(float),
        vol.Required("longitude"): vol.Coerce(float),
        vol.Required("requests"): [
            {
                vol.Required("provider"): str,
                vol.Required("capabilities"): [str],
            }
        ],
    }
)
@websocket_api.async_response
async def websocket_diagnostic_query(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Execute explicit point-value provider/capability requests for the Lab."""
    try:
        latitude = _coordinate(msg["latitude"], -90.0, 90.0)
        longitude = _coordinate(msg["longitude"], -180.0, 180.0)
    except (TypeError, ValueError, vol.Invalid) as err:
        connection.send_error(msg["id"], "invalid_coordinates", str(err))
        return

    providers = await _async_provider_catalog(hass)
    settings = _routing_settings(hass)
    results: list[dict[str, Any]] = []
    for item in msg["requests"]:
        provider_id = item["provider"]
        provider = providers.get(provider_id)
        if provider is None:
            results.append(
                {
                    "provider": provider_id,
                    "ok": False,
                    "error": "provider_not_available",
                }
            )
            continue

        capability_map = {capability.id: capability for capability in provider.capabilities()}
        requested = list(dict.fromkeys(item["capabilities"]))
        unsupported = [capability for capability in requested if capability not in capability_map]
        if unsupported:
            results.append(
                {
                    "provider": provider_id,
                    "ok": False,
                    "error": "unsupported_capability",
                    "unsupported": unsupported,
                }
            )
            continue

        blocked = [
            {
                "capability": capability,
                "reason": _capability_policy(
                    settings,
                    provider,
                    capability_map[capability],
                )[1],
            }
            for capability in requested
            if not _capability_policy(
                settings,
                provider,
                capability_map[capability],
            )[0]
        ]
        if blocked:
            results.append(
                {
                    "provider": provider_id,
                    "ok": False,
                    "error": blocked[0]["reason"] or "router_disabled",
                    "blocked": blocked,
                }
            )
            continue

        non_point = [
            capability
            for capability in requested
            if capability_map[capability].render_mode != "value"
        ]
        fetch_point = getattr(provider, "async_fetch_point", None)
        if non_point or not callable(fetch_point):
            results.append(
                {
                    "provider": provider_id,
                    "ok": False,
                    "error": "capability_not_point_value",
                    "unsupported": non_point or requested,
                }
            )
            continue

        try:
            provider_result = await fetch_point(hass, latitude, longitude, requested)
        except Exception as err:  # noqa: BLE001 - provider isolation is intentional here
            results.append(
                {
                    "provider": provider_id,
                    "ok": False,
                    "error": "provider_request_failed",
                    "detail": type(err).__name__,
                    "message": _redact_text(str(err)),
                }
            )
            continue

        results.append({"ok": True, **provider_result})

    connection.send_result(
        msg["id"],
        {
            "api_version": API_CONTRACT_VERSION,
            "request_location": {"latitude": latitude, "longitude": longitude},
            "results": results,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/map_layer",
        vol.Required("provider"): str,
        vol.Required("capability"): str,
    }
)
@websocket_api.async_response
async def websocket_map_layer(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one provider-backed map-layer descriptor for the Lab.

    The backend deliberately does not freeze map capabilities to raster tiles. Any
    non-value render mode may expose a descriptor through the same command; the Lab only
    renders modes it actually understands. This avoids another backend API change when
    vector/WMS/WMTS-style adapters are added later.
    """
    provider_id = msg["provider"]
    capability_id = msg["capability"]
    provider = (await _async_provider_catalog(hass)).get(provider_id)
    if provider is None:
        connection.send_error(msg["id"], "provider_not_available", provider_id)
        return

    capability = next(
        (item for item in provider.capabilities() if item.id == capability_id),
        None,
    )
    if capability is None:
        connection.send_error(msg["id"], "unsupported_capability", capability_id)
        return
    capability_allowed, capability_reason = _capability_policy(
        _routing_settings(hass),
        provider,
        capability,
    )
    if not capability_allowed:
        connection.send_error(
            msg["id"],
            capability_reason or "router_disabled",
            capability_id,
        )
        return
    if capability.render_mode == "value":
        connection.send_error(msg["id"], "unsupported_render_mode", capability.render_mode)
        return

    get_map_layer = getattr(provider, "async_get_map_layer", None)
    if not callable(get_map_layer):
        connection.send_error(msg["id"], "map_layer_not_available", provider_id)
        return

    try:
        layer = await get_map_layer(hass, capability_id)
    except Exception as err:  # noqa: BLE001 - provider isolation is intentional here
        connection.send_error(
            msg["id"],
            "provider_request_failed",
            f"{type(err).__name__}: {_redact_text(str(err))}",
        )
        return

    connection.send_result(
        msg["id"],
        {
            "api_version": API_CONTRACT_VERSION,
            "layer": layer,
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/biological_taxon_layer",
        vol.Required("scientific_name"): vol.All(
            str,
            vol.Length(min=2, max=200),
        ),
    }
)
@websocket_api.async_response
async def websocket_biological_taxon_layer(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Resolve one arbitrary GBIF taxon to a Lab-only occurrence-density layer."""
    provider = (await _async_provider_catalog(hass)).get("gbif_biodiversity")
    if provider is None:
        connection.send_error(msg["id"], "provider_not_available", "gbif_biodiversity")
        return

    allowed, reason = _provider_policy(_routing_settings(hass), provider)
    if not allowed:
        connection.send_error(
            msg["id"],
            reason or "router_disabled",
            "gbif_biodiversity",
        )
        return

    resolver = getattr(provider, "async_get_taxon_layer", None)
    if not callable(resolver):
        connection.send_error(
            msg["id"],
            "biological_taxon_search_not_available",
            "gbif_biodiversity",
        )
        return

    try:
        layer = await resolver(hass, msg["scientific_name"])
    except Exception as err:  # noqa: BLE001 - isolate provider/network failures
        connection.send_error(
            msg["id"],
            "provider_request_failed",
            f"{type(err).__name__}: {_redact_text(str(err))}",
        )
        return

    connection.send_result(
        msg["id"],
        {
            "api_version": API_CONTRACT_VERSION,
            "layer": layer,
        },
    )


def _hazard_bbox(raw: Any) -> tuple[float, float, float, float] | None:
    """Validate an optional [west, south, east, north] hazard viewport."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raise vol.Invalid("bbox must contain west,south,east,north")
    west, south, east, north = (float(item) for item in raw)
    if not all(isfinite(item) for item in (west, south, east, north)):
        raise vol.Invalid("bbox contains a non-finite coordinate")
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise vol.Invalid("bbox longitude out of range")
    if not (-90 <= south <= 90 and -90 <= north <= 90 and south <= north):
        raise vol.Invalid("bbox latitude out of range")
    return west, south, east, north


@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/event_feed",
        vol.Required("provider"): str,
        vol.Required("capability"): str,
        vol.Optional("latitude"): vol.Coerce(float),
        vol.Optional("longitude"): vol.Coerce(float),
        vol.Optional("bbox"): list,
        vol.Optional("limit", default=250): vol.All(
            vol.Coerce(int),
            vol.Range(min=1, max=1000),
        ),
    }
)
@websocket_api.async_response
async def websocket_event_feed(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one normalized non-warning observation event feed."""
    provider_id = msg["provider"]
    capability_id = msg["capability"]

    latitude = msg.get("latitude")
    longitude = msg.get("longitude")
    if (latitude is None) != (longitude is None):
        connection.send_error(
            msg["id"],
            "invalid_coordinates",
            "latitude and longitude must be supplied together",
        )
        return
    if latitude is not None:
        try:
            latitude = _coordinate(latitude, -90.0, 90.0)
            longitude = _coordinate(longitude, -180.0, 180.0)
        except (TypeError, ValueError, vol.Invalid) as err:
            connection.send_error(msg["id"], "invalid_coordinates", str(err))
            return

    try:
        bbox = _hazard_bbox(msg.get("bbox"))
    except (TypeError, ValueError, vol.Invalid) as err:
        connection.send_error(msg["id"], "invalid_bbox", str(err))
        return

    provider = (await _async_provider_catalog(hass)).get(provider_id)
    if provider is None:
        connection.send_error(msg["id"], "provider_not_available", provider_id)
        return

    capability = next(
        (item for item in provider.capabilities() if item.id == capability_id),
        None,
    )
    if capability is None:
        connection.send_error(msg["id"], "unsupported_capability", capability_id)
        return
    allowed, reason = _capability_policy(_routing_settings(hass), provider, capability)
    if not allowed:
        connection.send_error(msg["id"], reason or "router_disabled", capability_id)
        return
    if capability.render_mode != "event_feed":
        connection.send_error(
            msg["id"],
            "unsupported_render_mode",
            capability.render_mode,
        )
        return

    fetch = getattr(provider, "async_get_event_feed", None)
    if not callable(fetch):
        connection.send_error(msg["id"], "event_feed_not_available", provider_id)
        return

    try:
        feed = await fetch(
            hass,
            capability_id,
            latitude=latitude,
            longitude=longitude,
            bbox=bbox,
            limit=msg["limit"],
        )
    except Exception as err:  # noqa: BLE001
        connection.send_error(
            msg["id"],
            "provider_request_failed",
            f"{type(err).__name__}: {_redact_text(str(err))}",
        )
        return

    connection.send_result(
        msg["id"],
        {
            "api_version": API_CONTRACT_VERSION,
            "schema": "weather_router.event_feed.v1",
            "feed": _diagnostic_value(feed),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/hazard_feed",
        vol.Required("provider"): str,
        vol.Required("capability"): str,
        vol.Optional("latitude"): vol.Coerce(float),
        vol.Optional("longitude"): vol.Coerce(float),
        vol.Optional("bbox"): list,
        vol.Optional("limit", default=250): vol.All(
            vol.Coerce(int),
            vol.Range(min=1, max=1000),
        ),
    }
)
@websocket_api.async_response
async def websocket_hazard_feed(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one normalized official warning/event feed."""
    provider_id = msg["provider"]
    capability_id = msg["capability"]

    latitude = msg.get("latitude")
    longitude = msg.get("longitude")
    if (latitude is None) != (longitude is None):
        connection.send_error(
            msg["id"],
            "invalid_coordinates",
            "latitude and longitude must be supplied together",
        )
        return
    if latitude is not None:
        try:
            latitude = _coordinate(latitude, -90.0, 90.0)
            longitude = _coordinate(longitude, -180.0, 180.0)
        except (TypeError, ValueError, vol.Invalid) as err:
            connection.send_error(msg["id"], "invalid_coordinates", str(err))
            return

    try:
        bbox = _hazard_bbox(msg.get("bbox"))
    except (TypeError, ValueError, vol.Invalid) as err:
        connection.send_error(msg["id"], "invalid_bbox", str(err))
        return

    provider = (await _async_provider_catalog(hass)).get(provider_id)
    if provider is None:
        connection.send_error(msg["id"], "provider_not_available", provider_id)
        return

    capability = next(
        (item for item in provider.capabilities() if item.id == capability_id),
        None,
    )
    if capability is None:
        connection.send_error(msg["id"], "unsupported_capability", capability_id)
        return
    capability_allowed, capability_reason = _capability_policy(
        _routing_settings(hass),
        provider,
        capability,
    )
    if not capability_allowed:
        connection.send_error(
            msg["id"],
            capability_reason or "router_disabled",
            capability_id,
        )
        return
    if capability.render_mode != "hazard_feed":
        connection.send_error(
            msg["id"],
            "unsupported_render_mode",
            capability.render_mode,
        )
        return

    get_hazard_feed = getattr(provider, "async_get_hazard_feed", None)
    if not callable(get_hazard_feed):
        connection.send_error(msg["id"], "hazard_feed_not_available", provider_id)
        return

    try:
        feed = await get_hazard_feed(
            hass,
            capability_id,
            latitude=latitude,
            longitude=longitude,
            bbox=bbox,
            limit=msg["limit"],
        )
    except Exception as err:  # noqa: BLE001 - provider isolation is intentional here
        connection.send_error(
            msg["id"],
            "provider_request_failed",
            f"{type(err).__name__}: {_redact_text(str(err))}",
        )
        return

    connection.send_result(
        msg["id"],
        {
            "api_version": API_CONTRACT_VERSION,
            "schema": "weather_router.hazard_feed.v1",
            "feed": _diagnostic_value(feed),
        },
    )


def _event_feed_diagnostic_summary(feed: dict[str, Any]) -> dict[str, Any]:
    """Return a compact summary without exporting strike coordinates."""
    events = feed.get("events")
    if not isinstance(events, list):
        events = []
    latest = next(
        (
            item.get("observed_at")
            for item in events
            if isinstance(item, dict) and item.get("observed_at")
        ),
        None,
    )
    return {
        "provider": feed.get("provider"),
        "provider_name": feed.get("provider_name"),
        "provider_revision": feed.get("provider_revision"),
        "source_class": feed.get("source_class"),
        "render_mode": feed.get("render_mode"),
        "available": feed.get("available"),
        "event_count": feed.get("event_count", len(events)),
        "latest_observed_at": latest,
        "window_seconds": feed.get("window_seconds"),
        "source_status": _diagnostic_value(feed.get("source_status")),
        "attribution": feed.get("attribution"),
    }


def _hazard_feed_diagnostic_summary(feed: dict[str, Any]) -> dict[str, Any]:
    """Return a compact secret-safe summary of a normalized hazard feed."""
    events = feed.get("events")
    if not isinstance(events, list):
        events = []
    return {
        "provider": feed.get("provider"),
        "provider_name": feed.get("provider_name"),
        "provider_revision": feed.get("provider_revision"),
        "capability": feed.get("capability"),
        "source_class": feed.get("source_class"),
        "render_mode": feed.get("render_mode"),
        "coverage_status": feed.get("coverage_status"),
        "event_count": feed.get("event_count", len(events)),
        "hazard_types": sorted(
            {
                str(item.get("hazard_type"))
                for item in events
                if isinstance(item, dict) and item.get("hazard_type")
            }
        ),
        "sample": [
            {
                "id": item.get("id"),
                "hazard_type": item.get("hazard_type"),
                "event": item.get("event"),
                "headline": item.get("headline"),
                "severity": item.get("severity"),
                "expires": item.get("expires"),
                "has_geometry": isinstance(item.get("geometry"), dict),
            }
            for item in events[:10]
            if isinstance(item, dict)
        ],
        "attribution": feed.get("attribution"),
    }


def _data_file_diagnostic_summary(descriptor: dict[str, Any]) -> dict[str, Any]:
    """Return a compact data-file summary without exporting signed/query URLs."""
    raw_url = descriptor.get("url")
    host = None
    if isinstance(raw_url, str):
        try:
            from urllib.parse import urlsplit
            host = urlsplit(raw_url).hostname
        except ValueError:
            host = None
    return {
        "provider": descriptor.get("provider"),
        "provider_name": descriptor.get("provider_name"),
        "provider_revision": descriptor.get("provider_revision"),
        "capability": descriptor.get("capability"),
        "source_class": descriptor.get("source_class"),
        "render_mode": descriptor.get("render_mode"),
        "format": descriptor.get("format"),
        "content_type": descriptor.get("content_type"),
        "transport": descriptor.get("transport"),
        "size_bytes": descriptor.get("size_bytes"),
        "data_time": descriptor.get("data_time"),
        "satellite": descriptor.get("satellite"),
        "product": descriptor.get("product"),
        "coverage": descriptor.get("coverage"),
        "host": host,
        "provider_metadata": _diagnostic_value(descriptor.get("provider_metadata")),
    }


def _descriptor_diagnostic_summary(descriptor: dict[str, Any]) -> dict[str, Any]:
    """Return a compact secret-safe map descriptor summary for aggregate diagnostics."""
    summary: dict[str, Any] = {}
    for key in (
        "provider",
        "provider_name",
        "capability",
        "source_class",
        "render_mode",
        "frame_time",
        "tile_size",
        "max_zoom",
        "default_opacity",
        "network_hosts",
        "provider_metadata",
        "legend",
    ):
        if key in descriptor:
            summary[key] = _diagnostic_value(descriptor[key])

    timeline = descriptor.get("timeline")
    frames = timeline.get("frames") if isinstance(timeline, dict) else None
    if isinstance(frames, list):
        def _frame_brief(frame: Any) -> dict[str, Any] | None:
            if not isinstance(frame, dict):
                return None
            return {
                key: _diagnostic_value(frame[key])
                for key in ("time", "kind")
                if key in frame
            }

        summary["timeline"] = {
            "mode": timeline.get("mode"),
            "default": timeline.get("default"),
            "default_index": timeline.get("default_index"),
            "current_index": timeline.get("current_index"),
            "frame_count": len(frames),
            "first_frame": _frame_brief(frames[0]) if frames else None,
            "last_frame": _frame_brief(frames[-1]) if frames else None,
        }
    return summary


def _reference_diagnostic_context(
    hass: HomeAssistant,
) -> tuple[tuple[float, float] | None, dict[str, Any]]:
    """Resolve a private test coordinate while exporting only coarse reference metadata."""
    public = {
        "available": False,
        "has_coordinates": False,
        "domain": None,
    }
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime = getattr(entry, "runtime_data", None)
        resolver = getattr(runtime, "reference_context", None)
        if not callable(resolver):
            continue
        try:
            context = resolver()
        except Exception:  # noqa: BLE001 - aggregate diagnostics must continue
            continue
        public = {
            "available": bool(getattr(context, "available", False)),
            "has_coordinates": bool(getattr(context, "has_coordinates", False)),
            "domain": getattr(context, "domain", None),
        }
        latitude = getattr(context, "latitude", None)
        longitude = getattr(context, "longitude", None)
        if public["has_coordinates"] and latitude is not None and longitude is not None:
            return (float(latitude), float(longitude)), public
        return None, public
    return None, public


async def _async_aggregate_provider_report(
    hass: HomeAssistant,
    provider: Any,
    private_location: tuple[float, float] | None,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Run safe one-shot diagnostics without bypassing router eligibility."""
    capabilities = list(provider.capabilities())
    provider_allowed, provider_reason = _provider_policy(settings, provider)
    report: dict[str, Any] = {
        "id": provider.id,
        "name": provider.name,
        "capabilities": [
            {
                **_capability_info(item),
                "router_domain": _capability_domain(provider, item),
                "eligible": _capability_policy(settings, provider, item)[0],
                "disabled_reason": _capability_policy(settings, provider, item)[1],
                "machine_coverage_support": (
                    item.render_mode == "raster_tile"
                    and callable(getattr(provider, "async_get_coverage", None))
                ),
            }
            for item in capabilities
        ],
        "routing": {
            "eligible": provider_allowed,
            "disabled_reason": provider_reason,
            "domains": list(getattr(provider, "router_domains", ("weather",))),
            "enabled_by_user": provider.id in settings["enabled_providers"],
        },
        "info": _provider_info(provider),
        "network_targets": _network_targets(provider),
        "runtime_status": provider_runtime_summary(hass, provider.id),
        "provider_probe": None,
        "tests": [],
    }

    if not provider_allowed:
        report["provider_probe"] = {
            "ok": None,
            "status": "not_run",
            "reason": provider_reason or "router_disabled",
        }
        report["summary"] = {
            "ok": True,
            "provider_probe_failed": False,
            "tests_run": 0,
            "tests_failed": 0,
            "tests_skipped": len(capabilities),
            "routing_skipped": True,
        }
        return report

    eligible_capabilities = [
        item
        for item in capabilities
        if _capability_policy(settings, provider, item)[0]
    ]
    disabled_capabilities = [
        item
        for item in capabilities
        if not _capability_policy(settings, provider, item)[0]
    ]

    # Provider-wide probes may touch more than one capability. Only execute them
    # if every capability currently belongs to an enabled functional domain.
    provider_probe = getattr(provider, "async_diagnostics", None)
    if callable(provider_probe):
        if disabled_capabilities:
            report["provider_probe"] = {
                "ok": None,
                "status": "not_run",
                "reason": "domain_partially_disabled",
            }
        else:
            started = monotonic()
            try:
                probe_result = await provider_probe(hass, None)
                report["provider_probe"] = {
                    "ok": bool(probe_result.get("ok", True))
                    if isinstance(probe_result, dict)
                    else True,
                    "duration_ms": round((monotonic() - started) * 1000, 1),
                    "data": _diagnostic_value(probe_result),
                }
            except Exception as err:  # noqa: BLE001 - explicit diagnostics must capture failure
                report["provider_probe"] = {
                    "ok": False,
                    "duration_ms": round((monotonic() - started) * 1000, 1),
                    "exception": _exception_report(err),
                }

    for capability in disabled_capabilities:
        report["tests"].append(
            {
                "kind": (
                    "point_value"
                    if capability.render_mode == "value"
                    else "hazard_feed"
                    if capability.render_mode == "hazard_feed"
                    else "event_feed"
                    if capability.render_mode == "event_feed"
                    else "data_file"
                    if capability.render_mode == "data_file"
                    else "map_layer"
                ),
                "capability": capability.id,
                "name": capability.name,
                "render_mode": capability.render_mode,
                "source_class": capability.source_class,
                "ok": None,
                "status": "not_run",
                "reason": _capability_policy(settings, provider, capability)[1]
                or "domain_disabled",
            }
        )

    value_capabilities = [
        item for item in eligible_capabilities if item.render_mode == "value"
    ]
    if value_capabilities:
        test: dict[str, Any] = {
            "kind": "point_bundle",
            "capabilities": [item.id for item in value_capabilities],
        }
        started = monotonic()
        fetch_point = getattr(provider, "async_fetch_point", None)
        if private_location is None:
            test.update(
                {
                    "ok": None,
                    "status": "not_run",
                    "reason": "reference_location_has_no_coordinates",
                }
            )
        elif not callable(fetch_point):
            test.update(
                {
                    "ok": False,
                    "status": "point_provider_not_available",
                }
            )
        else:
            try:
                latitude, longitude = private_location
                point_result = await fetch_point(
                    hass,
                    latitude,
                    longitude,
                    [item.id for item in value_capabilities],
                )
                if isinstance(point_result, dict):
                    point_result = dict(point_result)
                    point_result.pop("latitude", None)
                    point_result.pop("longitude", None)
                test.update(
                    {
                        "ok": True,
                        "status": "point_values_created",
                        "result": _diagnostic_value(point_result),
                    }
                )
            except Exception as err:  # noqa: BLE001 - explicit diagnostics must capture failure
                test.update(
                    {
                        "ok": False,
                        "status": "exception",
                        "exception": _exception_report(err),
                    }
                )
        test["duration_ms"] = round((monotonic() - started) * 1000, 1)
        report["tests"].append(test)

    for capability in eligible_capabilities:
        if capability.render_mode == "value":
            continue
        test = {
            "kind": (
                "hazard_feed"
                if capability.render_mode == "hazard_feed"
                else "event_feed"
                if capability.render_mode == "event_feed"
                else "data_file"
                if capability.render_mode == "data_file"
                else "map_layer"
            ),
            "capability": capability.id,
            "name": capability.name,
            "render_mode": capability.render_mode,
            "source_class": capability.source_class,
        }
        started = monotonic()

        if capability.render_mode == "event_feed":
            get_event_feed = getattr(provider, "async_get_event_feed", None)
            if not callable(get_event_feed):
                test.update({"ok": False, "status": "event_feed_not_available"})
            else:
                try:
                    feed = await get_event_feed(
                        hass,
                        capability.id,
                        limit=25,
                    )
                    available = feed.get("available") is not False
                    test.update(
                        {
                            "ok": available,
                            "status": "event_feed_created" if available else "source_unavailable",
                            "feed": _event_feed_diagnostic_summary(feed),
                        }
                    )
                except Exception as err:  # noqa: BLE001
                    test.update(
                        {
                            "ok": False,
                            "status": "exception",
                            "exception": _exception_report(err),
                        }
                    )
        elif capability.render_mode == "hazard_feed":
            get_hazard_feed = getattr(provider, "async_get_hazard_feed", None)
            if not callable(get_hazard_feed):
                test.update({"ok": False, "status": "hazard_feed_not_available"})
            else:
                try:
                    feed = await get_hazard_feed(
                        hass,
                        capability.id,
                        limit=25,
                    )
                    test.update(
                        {
                            "ok": True,
                            "status": "hazard_feed_created",
                            "feed": _hazard_feed_diagnostic_summary(feed),
                        }
                    )
                except Exception as err:  # noqa: BLE001 - explicit diagnostics must capture failure
                    test.update(
                        {
                            "ok": False,
                            "status": "exception",
                            "exception": _exception_report(err),
                        }
                    )
        elif capability.render_mode == "data_file":
            get_data_file = getattr(provider, "async_get_data_file", None)
            if not callable(get_data_file):
                test.update({"ok": False, "status": "data_file_not_available"})
            else:
                try:
                    descriptor = await get_data_file(hass, capability.id)
                    test.update(
                        {
                            "ok": True,
                            "status": "data_file_resolved",
                            "descriptor": _data_file_diagnostic_summary(descriptor),
                        }
                    )
                except Exception as err:  # noqa: BLE001
                    test.update(
                        {
                            "ok": False,
                            "status": "exception",
                            "exception": _exception_report(err),
                        }
                    )
        else:
            get_map_layer = getattr(provider, "async_get_map_layer", None)
            if not callable(get_map_layer):
                test.update(
                    {
                        "ok": False,
                        "status": "map_layer_not_available",
                    }
                )
            else:
                try:
                    coverage_getter = getattr(provider, "async_get_coverage", None)
                    if capability.render_mode == "raster_tile":
                        test["machine_coverage_support"] = callable(coverage_getter)
                        if callable(coverage_getter):
                            coverage_started = monotonic()
                            coverage = await coverage_getter(hass, capability.id)
                            test["machine_coverage"] = _diagnostic_value(coverage)
                            test["coverage_duration_ms"] = round(
                                (monotonic() - coverage_started) * 1000,
                                1,
                            )
                    descriptor = await get_map_layer(hass, capability.id)
                    test.update(
                        {
                            "ok": True,
                            "status": "descriptor_created",
                            "descriptor": _descriptor_diagnostic_summary(descriptor),
                        }
                    )
                except Exception as err:  # noqa: BLE001 - explicit diagnostics must capture failure
                    test.update(
                        {
                            "ok": False,
                            "status": "exception",
                            "exception": _exception_report(err),
                        }
                    )
        test["duration_ms"] = round((monotonic() - started) * 1000, 1)
        report["tests"].append(test)

    failed = [item for item in report["tests"] if item.get("ok") is False]
    skipped = [item for item in report["tests"] if item.get("ok") is None]
    probe_failed = (
        report["provider_probe"] is not None
        and report["provider_probe"].get("ok") is False
    )
    report["summary"] = {
        "ok": not failed and not probe_failed,
        "provider_probe_failed": probe_failed,
        "tests_run": len(report["tests"]) - len(skipped),
        "tests_failed": len(failed),
        "tests_skipped": len(skipped),
        "routing_skipped": False,
    }
    return report


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/all_provider_diagnostics",
        vol.Optional("provider"): str,
    }
)
@websocket_api.async_response
async def websocket_all_provider_diagnostics(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run one aggregate diagnostic covering every currently registered provider."""
    providers = await _async_provider_catalog(hass)
    provider_filter = msg.get("provider")
    if provider_filter is not None:
        selected = providers.get(provider_filter)
        if selected is None:
            connection.send_error(
                msg["id"],
                "provider_not_available",
                provider_filter,
            )
            return
        providers = {provider_filter: selected}

    settings = _routing_settings(hass)
    private_location, reference_public = _reference_diagnostic_context(hass)
    reports: list[dict[str, Any]] = []

    for provider in providers.values():
        reports.append(
            await _async_aggregate_provider_report(
                hass,
                provider,
                private_location,
                settings,
            )
        )

    failed = [item for item in reports if item["summary"]["ok"] is False]
    skipped_providers = [
        item for item in reports if item["summary"].get("routing_skipped") is True
    ]
    tested_providers = [
        item for item in reports if item["summary"].get("routing_skipped") is not True
    ]
    tests_run = sum(item["summary"]["tests_run"] for item in reports)
    tests_failed = sum(item["summary"]["tests_failed"] for item in reports)
    tests_skipped = sum(item["summary"]["tests_skipped"] for item in reports)

    connection.send_result(
        msg["id"],
        _diagnostic_value(
            {
                "schema": "weather_router.all_provider_diagnostics.v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "api_version": API_CONTRACT_VERSION,
                "reference_context": reference_public,
                "providers": reports,
                "summary": {
                    "ok": not failed,
                    "router_enabled": settings["router_enabled"],
                    "provider_count": len(reports),
                    "providers_tested": len(tested_providers),
                    "providers_skipped": len(skipped_providers),
                    "providers_ok": len(tested_providers) - len(failed),
                    "providers_failed": len(failed),
                    "tests_run": tests_run,
                    "tests_failed": tests_failed,
                    "tests_skipped": tests_skipped,
                },
            }
        ),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/provider_diagnostics",
        vol.Required("provider"): str,
        vol.Optional("capability"): str,
    }
)
@websocket_api.async_response
async def websocket_provider_diagnostics(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run an explicit one-shot provider diagnostic and return structured JSON.

    This endpoint is intentionally admin-only and on-demand. It creates no polling,
    background task or persistent diagnostic state. Output is recursively redacted.
    """
    provider_id = msg["provider"]
    capability_id = msg.get("capability")
    providers = await _async_provider_catalog(hass)
    provider = providers.get(provider_id)
    if provider is None:
        connection.send_error(msg["id"], "provider_not_available", provider_id)
        return

    capabilities = list(provider.capabilities())
    capability_map = {item.id: item for item in capabilities}
    if capability_id is not None and capability_id not in capability_map:
        connection.send_error(msg["id"], "unsupported_capability", capability_id)
        return

    settings = _routing_settings(hass)
    if capability_id is None:
        allowed, disabled_reason = _provider_policy(settings, provider)
        if allowed:
            disabled_capabilities = [
                item
                for item in capabilities
                if not _capability_policy(settings, provider, item)[0]
            ]
            if disabled_capabilities:
                allowed = False
                disabled_reason = "domain_partially_disabled"
    else:
        allowed, disabled_reason = _capability_policy(
            settings,
            provider,
            capability_map[capability_id],
        )
    if not allowed:
        connection.send_error(
            msg["id"],
            disabled_reason or "router_disabled",
            provider_id if capability_id is None else capability_id,
        )
        return

    report: dict[str, Any] = {
        "schema": "weather_router.provider_diagnostics.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_version": API_CONTRACT_VERSION,
        "provider": {
            "id": provider.id,
            "name": provider.name,
            "capabilities": [
                {
                    **_capability_info(item),
                    "machine_coverage_support": (
                        item.render_mode == "raster_tile"
                        and callable(getattr(provider, "async_get_coverage", None))
                    ),
                }
                for item in capabilities
            ],
            "info": _provider_info(provider),
            "network_targets": _network_targets(provider),
            "runtime_status": provider_runtime_summary(hass, provider.id),
        },
        "scope": {
            "capability": capability_id,
            "mode": "capability" if capability_id else "provider",
        },
        "provider_probe": None,
        "tests": [],
    }

    provider_probe = getattr(provider, "async_diagnostics", None)
    if callable(provider_probe):
        started = monotonic()
        try:
            probe_result = await provider_probe(hass, capability_id)
            report["provider_probe"] = {
                "ok": bool(probe_result.get("ok", True))
                if isinstance(probe_result, dict)
                else True,
                "duration_ms": round((monotonic() - started) * 1000, 1),
                "data": _diagnostic_value(probe_result),
            }
        except Exception as err:  # noqa: BLE001 - diagnostics must capture provider failures
            report["provider_probe"] = {
                "ok": False,
                "duration_ms": round((monotonic() - started) * 1000, 1),
                "exception": _exception_report(err),
            }

    test_capability = capability_id
    if test_capability is None:
        test_capability = next(
            (item.id for item in capabilities if item.render_mode != "value"),
            None,
        )

    if test_capability is not None:
        capability = capability_map[test_capability]
        test: dict[str, Any] = {
            "capability": capability.id,
            "name": capability.name,
            "render_mode": capability.render_mode,
            "source_class": capability.source_class,
        }
        started = monotonic()

        if capability.render_mode == "value":
            test.update(
                {
                    "ok": None,
                    "status": "not_run",
                    "reason": "point_value_requires_explicit_location",
                }
            )
        elif capability.render_mode == "event_feed":
            get_event_feed = getattr(provider, "async_get_event_feed", None)
            if not callable(get_event_feed):
                test.update(
                    {
                        "ok": False,
                        "status": "event_feed_not_available",
                    }
                )
            else:
                try:
                    feed = await get_event_feed(
                        hass,
                        capability.id,
                        limit=25,
                    )
                    available = feed.get("available") is not False
                    test.update(
                        {
                            "ok": available,
                            "status": "event_feed_created" if available else "source_unavailable",
                            "feed": _event_feed_diagnostic_summary(feed),
                        }
                    )
                except Exception as err:  # noqa: BLE001
                    test.update(
                        {
                            "ok": False,
                            "status": "exception",
                            "exception": _exception_report(err),
                        }
                    )
        elif capability.render_mode == "hazard_feed":
            get_hazard_feed = getattr(provider, "async_get_hazard_feed", None)
            if not callable(get_hazard_feed):
                test.update(
                    {
                        "ok": False,
                        "status": "hazard_feed_not_available",
                    }
                )
            else:
                try:
                    feed = await get_hazard_feed(
                        hass,
                        capability.id,
                        limit=25,
                    )
                    test.update(
                        {
                            "ok": True,
                            "status": "hazard_feed_created",
                            "feed": _hazard_feed_diagnostic_summary(feed),
                        }
                    )
                except Exception as err:  # noqa: BLE001 - full explicit diagnostic capture
                    test.update(
                        {
                            "ok": False,
                            "status": "exception",
                            "exception": _exception_report(err),
                        }
                    )
        elif capability.render_mode == "data_file":
            get_data_file = getattr(provider, "async_get_data_file", None)
            if not callable(get_data_file):
                test.update(
                    {
                        "ok": False,
                        "status": "data_file_not_available",
                    }
                )
            else:
                try:
                    descriptor = await get_data_file(hass, capability.id)
                    test.update(
                        {
                            "ok": True,
                            "status": "data_file_resolved",
                            "descriptor": _data_file_diagnostic_summary(descriptor),
                        }
                    )
                except Exception as err:  # noqa: BLE001
                    test.update(
                        {
                            "ok": False,
                            "status": "exception",
                            "exception": _exception_report(err),
                        }
                    )
        else:
            get_map_layer = getattr(provider, "async_get_map_layer", None)
            if not callable(get_map_layer):
                test.update(
                    {
                        "ok": False,
                        "status": "map_layer_not_available",
                    }
                )
            else:
                try:
                    coverage_getter = getattr(provider, "async_get_coverage", None)
                    if capability.render_mode == "raster_tile":
                        test["machine_coverage_support"] = callable(coverage_getter)
                        if callable(coverage_getter):
                            coverage_started = monotonic()
                            coverage = await coverage_getter(hass, capability.id)
                            test["machine_coverage"] = _diagnostic_value(coverage)
                            test["coverage_duration_ms"] = round(
                                (monotonic() - coverage_started) * 1000,
                                1,
                            )
                    descriptor = await get_map_layer(hass, capability.id)
                    test.update(
                        {
                            "ok": True,
                            "status": "descriptor_created",
                            "descriptor": _diagnostic_value(descriptor),
                        }
                    )
                except Exception as err:  # noqa: BLE001 - full explicit diagnostic capture
                    test.update(
                        {
                            "ok": False,
                            "status": "exception",
                            "exception": _exception_report(err),
                        }
                    )

        test["duration_ms"] = round((monotonic() - started) * 1000, 1)
        report["tests"].append(test)

    explicit_failures = [
        item
        for item in report["tests"]
        if item.get("ok") is False
    ]
    probe_failed = report["provider_probe"] is not None and report["provider_probe"].get("ok") is False
    report["summary"] = {
        "ok": not explicit_failures and not probe_failed,
        "provider_probe_failed": probe_failed,
        "tests_run": len(report["tests"]),
        "tests_failed": len(explicit_failures),
    }

    connection.send_result(msg["id"], _diagnostic_value(report))



_ARCHIVE_REPO = "TheDaimos/Project-Log-And-Export"
_ARCHIVE_TOKEN_KEY = "log_archive_token"
_ARCHIVE_BRANCH_KEY = "log_archive_branch"
_DEFAULT_GIT_TARGET_KEY = "log_git_default_target"


def _git_default_target(entry: Any) -> str:
    """Diagnostic exports are permanently isolated from source repositories.

    Ignore legacy choices of "wr" without altering saved credentials.
    """
    return "archive"


def _git_target(
    msg: dict[str, Any], entry: Any | None = None,
) -> tuple[str, str, str, str, bool]:
    target = msg.get("target") or "archive"
    if target == "archive":
        return _ARCHIVE_REPO, _ARCHIVE_TOKEN_KEY, _ARCHIVE_BRANCH_KEY, "exports/weather-router", True
    if target == "wr":
        raise WeatherRouterLogExportError(
            "Git-WR is not an authorized diagnostic destination; use Project-Log-And-Export"
        )
    raise WeatherRouterLogExportError("unknown export target")


def _git_state(entry: Any, msg: dict[str, Any]) -> dict[str, Any]:
    target = msg.get("target") or "archive"
    if target == "wr":
        return {
            "configured": False,
            "repository": LOG_GIT_REPOSITORY,
            "branch": None,
            "root": LOG_GIT_ROOT,
            "target": "wr",
            "default_target": "archive",
            "is_default": False,
            "retired": True,
            "legacy_token_saved": bool(entry.data.get(CONF_LOG_GIT_TOKEN)),
        }
    repo, token_key, branch_key, root, _ = _git_target(msg, entry)
    return {
        "configured": bool(entry.data.get(token_key) and entry.data.get(branch_key)),
        "repository": repo,
        "branch": entry.data.get(branch_key),
        "root": root,
        "target": "archive",
        "default_target": "archive",
        "is_default": True,
        "retired": False,
    }


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "weather_router/log_git_status",
    vol.Optional("target"): vol.In(["wr", "archive"]),
})
def websocket_log_git_status(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        entry = _weather_router_entry(hass)
        connection.send_result(msg["id"], _git_state(entry, msg))
    except WeatherRouterLogExportError as err:
        connection.send_error(msg["id"], "not_configured", str(err))


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "weather_router/log_git_configure",
    vol.Optional("target"): vol.In(["wr", "archive"]),
    vol.Optional("repository", default=""): str,
    vol.Optional("token", default=""): str,
    vol.Optional("clear", default=False): bool,
})
@websocket_api.async_response
async def websocket_log_git_configure(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        entry = _weather_router_entry(hass)
        data = dict(entry.data)
        if msg.get("target") == "wr":
            if not msg.get("clear"):
                raise WeatherRouterLogExportError(
                    "Git-WR credential setup is retired; diagnostic exports are archive-only"
                )
            data.pop(CONF_LOG_GIT_TOKEN, None)
            data.pop(CONF_LOG_GIT_BRANCH, None)
            hass.config_entries.async_update_entry(entry, data=data)
            connection.send_result(msg["id"], _git_state(entry, {"target": "wr"}) | {
                "legacy_token_saved": False,
            })
            return
        repo, token_key, branch_key, root, private = _git_target(msg, entry)
        requested = str(msg.get("repository") or repo).strip().removeprefix("https://github.com/").rstrip("/")
        if requested != repo:
            raise WeatherRouterLogExportError("Repository does not match the allowed destination")
        if msg.get("clear"):
            data.pop(token_key, None)
            data.pop(branch_key, None)
        else:
            token = str(msg.get("token") or "").strip() or str(data.get(token_key) or "").strip()
            if not token:
                raise WeatherRouterLogExportError("GitHub write token is required")
            client = WeatherRouterLogGitClient(async_get_clientsession(hass), token, repository=repo, root=root, require_private=private)
            info = await client.async_repository()
            data[token_key] = token
            data[branch_key] = info["default_branch"]
        hass.config_entries.async_update_entry(entry, data=data)
        connection.send_result(msg["id"], _git_state(entry, {**msg, "target": msg.get("target") or _git_default_target(entry)}) | {
            "configured": bool(data.get(token_key) and data.get(branch_key)),
            "branch": data.get(branch_key),
        })
    except WeatherRouterLogExportError as err:
        connection.send_error(msg["id"], "git_export_config_failed", str(err))


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "weather_router/log_git_set_default",
    vol.Required("target"): vol.In(["wr", "archive"]),
})
def websocket_log_git_set_default(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Only the isolated private archive may be the diagnostic default."""
    try:
        entry = _weather_router_entry(hass)
        target = msg["target"]
        if target != "archive":
            raise WeatherRouterLogExportError(
                "Project repositories cannot be selected for diagnostic exports"
            )
        data = dict(entry.data)
        data[_DEFAULT_GIT_TARGET_KEY] = "archive"
        hass.config_entries.async_update_entry(entry, data=data)
        connection.send_result(
            msg["id"], _git_state(entry, {**msg, "target": target}) | {
                "default_target": target,
                "is_default": True,
            },
        )
    except WeatherRouterLogExportError as err:
        connection.send_error(msg["id"], "git_default_failed", str(err))


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "weather_router/log_git_export",
    vol.Required("snapshot"): dict,
    vol.Optional("target"): vol.In(["wr", "archive"]),
})
@websocket_api.async_response
async def websocket_log_git_export(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        entry = _weather_router_entry(hass)
        repo, token_key, branch_key, root, private = _git_target(msg, entry)
        if repo != _ARCHIVE_REPO or not private:
            raise WeatherRouterLogExportError("Diagnostic destination is not isolated")
        token = str(entry.data.get(token_key) or "").strip()
        branch = str(entry.data.get(branch_key) or "").strip()
        if not token or not branch:
            raise WeatherRouterLogExportError("Configure this Git export target first")

        snapshot = _diagnostic_value(msg["snapshot"])
        schema = snapshot.get("schema")
        supported_schemas = {
            "weather_router.event_log.v1",
            "weather_router.provider_diagnostics.v1",
            "weather_router.all_provider_diagnostics.v1",
            ROUTING_DIAGNOSTIC_SCHEMA,
            "weather_router.api_monitor.v1",
            "weather_router.opera_status.v1",
        }
        if schema not in supported_schemas:
            raise WeatherRouterLogExportError("unsupported WeatherRouter diagnostic schema")

        if schema == "weather_router.event_log.v1":
            events = snapshot.get("events")
            if not isinstance(events, list) or len(events) > 500:
                raise WeatherRouterLogExportError("invalid WeatherRouter event log")
        elif schema == "weather_router.provider_diagnostics.v1":
            tests = snapshot.get("tests")
            if tests is not None and not isinstance(tests, list):
                raise WeatherRouterLogExportError("invalid provider diagnostic tests")
        elif schema == "weather_router.all_provider_diagnostics.v1":
            providers = snapshot.get("providers")
            if providers is not None and not isinstance(providers, list):
                raise WeatherRouterLogExportError("invalid aggregate provider diagnostics")
        elif schema == "weather_router.opera_status.v1":
            opera = snapshot.get("opera")
            if not isinstance(opera, dict) or not isinstance(opera.get("products"), dict):
                raise WeatherRouterLogExportError("invalid OPERA diagnostic snapshot")
            if snapshot.get("captured_at_utc") is None:
                raise WeatherRouterLogExportError("missing OPERA capture timestamp")
        elif schema == "weather_router.api_monitor.v1":
            entries = snapshot.get("entries")
            if not isinstance(entries, list) or len(entries) > 250:
                raise WeatherRouterLogExportError("invalid API monitor entries")
            if any(not isinstance(item, dict) for item in entries):
                raise WeatherRouterLogExportError("invalid API monitor entry")
        elif schema == ROUTING_DIAGNOSTIC_SCHEMA:
            candidates = snapshot.get("candidates")
            if not isinstance(candidates, list) or len(candidates) > 200:
                raise WeatherRouterLogExportError("invalid routing diagnostic candidates")
            if not isinstance(snapshot.get("decision"), dict):
                raise WeatherRouterLogExportError("invalid routing diagnostic decision")

        encoded_size = len(
            json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        if encoded_size > 2 * 1024 * 1024:
            raise WeatherRouterLogExportError("WeatherRouter log exceeds 2 MiB")

        client = WeatherRouterLogGitClient(async_get_clientsession(hass), token, repository=repo, root=root, require_private=private)
        info = await client.async_repository()
        if not info["private"]:
            raise WeatherRouterLogExportError("Diagnostic export blocked: destination is public")
        result = await client.async_export(snapshot, branch=branch)
        connection.send_result(msg["id"], result)
    except WeatherRouterLogExportError as err:
        connection.send_error(msg["id"], "git_export_failed", str(err))

@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "weather_router/opera_status"})
@websocket_api.async_response
async def websocket_opera_status(hass, connection, msg):
    """Admin-only live OPERA status; never returns tokens or local paths."""
    runtime = hass.data.get(DOMAIN, {}).get("opera_runtime")
    if runtime is None:
        connection.send_result(msg["id"], {
            "provider_enabled": False,
            "scientific_status": "UNVERIFIED/BLOCKED",
            "http_enabled": False, "consumer_v2_approved": False,
            "runtime_present": False, "products": {},
        })
        return
    status = runtime.status()
    monitor = hass.data.get(DOMAIN, {}).get("opera_source_monitor")
    status["source_monitor"] = {
        "running": bool(monitor and monitor._task is not None and not monitor._task.done()),
        "last_success_utc": monitor.last_success_utc.isoformat() if monitor and monitor.last_success_utc else None,
        "last_original": monitor.last_object if monitor else None,
        "active_downloads": monitor.active_downloads if monitor else 0,
        "last_reason": monitor.last_reason if monitor else "provider_disabled",
    }
    status["runtime_present"] = True
    status["scientific_status"] = "UNVERIFIED/BLOCKED"
    connection.send_result(msg["id"], status)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "weather_router/opera_refresh"})
@websocket_api.async_response
async def websocket_opera_refresh(hass, connection, msg):
    """Run the SAME bounded source monitor, never a second test pipeline."""
    monitor = hass.data.get(DOMAIN, {}).get("opera_source_monitor")
    if monitor is None or monitor.runtime.enabled is not True:
        connection.send_error(msg["id"], "opera_disabled", "OPERA provider is disabled.")
        return
    await monitor.check_once()
    connection.send_result(msg["id"], {"status": monitor.last_reason,
                                       "active_downloads": monitor.active_downloads})


def async_register(hass: HomeAssistant) -> None:
    """Register WeatherRouter WebSocket commands."""
    websocket_api.async_register_command(hass, websocket_opera_status)
    websocket_api.async_register_command(hass, websocket_opera_refresh)
    websocket_api.async_register_command(hass, websocket_routing_settings)
    websocket_api.async_register_command(hass, websocket_routing_settings_update)
    websocket_api.async_register_command(hass, websocket_consumer_profiles)
    websocket_api.async_register_command(hass, websocket_consumer_profile_upsert)
    websocket_api.async_register_command(hass, websocket_consumer_profile_delete)
    websocket_api.async_register_command(hass, websocket_providers)
    websocket_api.async_register_command(hass, websocket_diagnostic_query)
    websocket_api.async_register_command(hass, websocket_map_layer)
    websocket_api.async_register_command(hass, websocket_hazard_feed)
    websocket_api.async_register_command(hass, websocket_event_feed)
    websocket_api.async_register_command(hass, websocket_provider_diagnostics)
    websocket_api.async_register_command(hass, websocket_all_provider_diagnostics)
    websocket_api.async_register_command(hass, websocket_log_git_status)
    websocket_api.async_register_command(hass, websocket_log_git_configure)
    websocket_api.async_register_command(hass, websocket_log_git_set_default)
    websocket_api.async_register_command(hass, websocket_log_git_export)
