"""Privacy-conscious Home Assistant Config Entry diagnostics for WeatherRouter."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import WeatherRouterConfigEntry
from .const import (
    API_CONTRACT_VERSION,
    CONSUMER_CONTRACT_VERSION,
    DEV_BUILD_VERSION,
    DEV_LOADER_REV,
    INTEGRATION_VERSION,
    ROUTER_DOMAINS,
)
from .consumer_api import _load_mapping_sync
from .providers import provider_catalog
from .routing_diagnostics import routing_diagnostic_summary


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: WeatherRouterConfigEntry,
) -> dict[str, Any]:
    """Return bounded diagnostics without exporting exact private coordinates."""
    runtime = entry.runtime_data
    reference = runtime.reference_context()
    routing = runtime.routing_settings()

    providers = await hass.async_add_executor_job(provider_catalog)
    mapping = await hass.async_add_executor_job(_load_mapping_sync)
    profiles_getter = getattr(runtime, "consumer_profiles", None)
    profiles = profiles_getter() if callable(profiles_getter) else {}
    routing_summary = routing_diagnostic_summary(hass)

    extension_count = sum(
        1
        for provider in providers.values()
        if getattr(provider, "weather_router_extension_id", None)
    )
    public_capabilities = mapping.get("public_capabilities", {})
    enabled_provider_ids = set(routing["enabled_providers"])

    return {
        "schema": "weather_router.config_entry_diagnostics.v2",
        "config_entry": {
            "version": entry.version,
            "minor_version": entry.minor_version,
        },
        "versions": {
            "integration_manifest": INTEGRATION_VERSION,
            "weather_router_build": DEV_BUILD_VERSION,
            "loader": DEV_LOADER_REV,
            "diagnostic_api": API_CONTRACT_VERSION,
            "consumer_contract": CONSUMER_CONTRACT_VERSION,
            "routing_diagnostic_schema": "weather_router.routing_diagnostic.v1",
        },
        "router": {
            "development_stage": "consumer_api_v1_active",
            "loaded": True,
            "runtime_ready": runtime is not None,
            "enabled": routing["router_enabled"],
            "enabled_domains": list(routing["enabled_domains"]),
            "domain_count": len(ROUTER_DOMAINS),
            "provider_count": len(providers),
            "enabled_provider_count": sum(
                1 for provider_id in providers if provider_id in enabled_provider_ids
            ),
            "extension_count": extension_count,
            "public_capability_count": len(public_capabilities)
            if isinstance(public_capabilities, dict)
            else None,
            "consumer_profile_count": len(profiles)
            if isinstance(profiles, dict)
            else None,
        },
        "reference_location": {
            "domain": reference.domain,
            "available": reference.available,
            "has_coordinates": reference.has_coordinates,
            # Exact coordinates and entity identifiers intentionally remain absent.
        },
        "cache_statistics": {
            "routing_trace_ring": {
                "entries": routing_summary["stored_trace_count"],
                "limit": routing_summary["ring_limit"],
            },
            "provider_caches": "provider_specific_not_polled_in_config_diagnostics",
        },
        "routing_diagnostics": {
            "status_counts": routing_summary["status_counts"],
            "last_success": routing_summary["last_success"],
            "error_classes": routing_summary["error_classes"],
        },
    }
