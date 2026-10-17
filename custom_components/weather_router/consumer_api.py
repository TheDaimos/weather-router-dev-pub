"""Implemented read-only WeatherRouter Consumer API V1.

This module is intentionally separate from the internal Lab/diagnostic WebSocket API.
It exposes provider-neutral capabilities and keeps provider identity in provenance only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import json
from math import isfinite
from pathlib import Path
import re
from time import monotonic
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ENABLED_DOMAINS,
    CONF_ENABLED_PROVIDERS,
    CONF_CONSUMER_PROFILES,
    CONF_ROUTER_ENABLED,
    CONSUMER_CONTRACT_NAME,
    CONSUMER_CONTRACT_VERSION,
    DOMAIN,
    INTEGRATION_VERSION,
    ROUTER_DOMAINS,
)
from .extensions import merge_extension_capability_map
from .consumer_profiles import (
    PROFILE_ID_RE,
    apply_profile_event_filter,
    profile_allows_capability,
    profile_allows_candidate,
    profile_allows_provider,
    profile_reference,
)
from .providers import provider_catalog
from .providers.hazard_common import geometry_intersects_bbox_strict, point_in_geometry
from .consumer_routing_policy import candidate_score, normalized_candidate_semantics
from .consumer_time_contract import validate_time_semantics_contract
from .routing_diagnostic_core import redact_text
from .routing_diagnostics import RoutingTrace, begin_routing_trace
from .wind_semantics import normalize_shared_wind_value
from .snow_semantics import normalize_snowfall_value
from .visibility_semantics import normalize_visibility_value
from .uv_semantics import normalize_uv_index_value
from .lightning_semantics import (
    apply_lightning_resource_semantics,
    normalize_lightning_value,
)
from .thunder_semantics import (
    apply_thunder_resource_semantics,
    normalize_thunder_value,
)
from .spatial_coverage import (
    context_diagnostics,
    coverage_diagnostics,
    coverage_matches_context,
    normalize_coverage,
)

_CONSUMER_MAP_PATH = Path(__file__).with_name("consumer_capability_map.json")
_HAZARD_TYPES_PATH = Path(__file__).with_name("consumer_hazard_event_types.json")
_SENSITIVE_QUERY_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "token",
    "key",
    "appid",
    "password",
    "secret",
    "authorization",
}
_PUBLIC_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
_DIAGNOSTIC_FAULTS_KEY = f"{DOMAIN}_routing_diagnostic_faults"
_DIAGNOSTIC_FAULT_TTL_SECONDS = 120.0
_DIAGNOSTIC_FAULT_MODES = {
    "resource_temporarily_unavailable",
    "rate_limited",
    "source_stale",
}
_RESOURCE_TYPES = frozenset(
    {
        "value",
        "raster_tile",
        "hazard_feed",
        "event_feed",
        "image_sequence",
        "live_stream",
        "planetary_tile",
        "data_file",
    }
)

_FLOOD_SEMANTIC_PUBLIC_IDS = frozenset(
    {
        "weather.warning.official",
        "natural_hazards.flood.warning",
        "civil_protection.warning.official",
    }
)
_FLOOD_SEMANTIC_CLASSES = (
    "official_flood_alert_event",
    "official_flash_flood_alert_event",
    "official_surface_water_flood_alert_event",
    "official_debris_flow_alert_event",
    "official_levee_failure_alert_event",
    "official_dam_failure_alert_event",
    "official_glof_alert_event",
    "official_ice_jam_flood_alert_event",
)
_FLOOD_MATCH_SCOPES = ("explicit_event", "contextual_text")

_TROPICAL_SYSTEM_PUBLIC_IDS = frozenset(
    {
        "natural_hazards.tropical_cyclone.events",
        "weather.warning.official",
        "natural_hazards.disaster_awareness.events",
        "aviation.airmet.us",
        "aviation.gairmet.us",
        "aviation.sigmet.international",
    }
)
_TROPICAL_SYSTEM_CLASSES = (
    "potential_tropical_cyclone",
    "tropical_depression",
    "tropical_storm",
    "hurricane_strength_tropical_cyclone",
    "subtropical_cyclone",
    "post_tropical_cyclone",
    "tropical_cyclone_unspecified",
)
_TROPICAL_REGIONAL_TERMS = (
    "hurricane",
    "typhoon",
    "cyclone",
    "severe_tropical_cyclone",
)
_TROPICAL_CLASSIFICATION_SOURCES = (
    "structured_provider_field",
    "explicit_event_text",
)


_AVIATION_PUBLIC_IDS = frozenset(
    {
        "aviation.airmet.us",
        "aviation.gairmet.us",
        "aviation.sigmet.international",
    }
)

_CIVIL_PROTECTION_PUBLIC_IDS = frozenset(
    {
        "civil_protection.warning.official",
    }
)

_SECURITY_PUBLIC_IDS = frozenset(
    {
        "security.public_warning.official",
    }
)

_POINT_GEOMETRY_REQUIRED_PUBLIC_IDS = (
    _CIVIL_PROTECTION_PUBLIC_IDS | _SECURITY_PUBLIC_IDS
)


_EARTHQUAKE_PUBLIC_IDS = frozenset(
    {
        "natural_hazards.earthquake.events",
        "natural_hazards.earthquake.significant_events",
    }
)
_EARTHQUAKE_SEMANTIC_CLASSES = (
    "seismic_catalog_earthquake_event",
    "disaster_awareness_earthquake_event",
)
_EARTHQUAKE_CATALOG_SELECTIONS = ("all_day", "significant_month")


_VOLCANO_PUBLIC_IDS = frozenset(
    {
        "natural_hazards.volcano.activity",
        "natural_hazards.volcano.warnings",
    }
)
_VOLCANO_SEMANTIC_CLASSES = (
    "weekly_volcanic_activity_report_event",
    "official_volcano_status_event",
    "disaster_awareness_volcanic_event",
    "seismic_catalog_volcanic_event",
)

_TSUNAMI_SEMANTIC_PUBLIC_IDS = frozenset(
    {
        "natural_hazards.tsunami.warnings",
        "natural_hazards.tsunami.observations",
        "natural_hazards.tsunami.potential",
        "natural_hazards.disaster_awareness.events",
    }
)
_TSUNAMI_ALERT_STAGE_PUBLIC_IDS = frozenset({"natural_hazards.tsunami.warnings"})
_TSUNAMI_SEMANTIC_CLASSES = (
    "official_tsunami_warning_event",
    "tsunami_observation_event",
    "tsunami_potential_indicator_event",
    "disaster_awareness_tsunami_event",
)
_TSUNAMI_ALERT_STAGES = (
    "warning", "advisory", "watch", "threat", "marine_warning",
    "land_inundation_warning", "information", "no_threat", "canceled",
)
_TSUNAMI_WAVE_EVIDENCE = ("expected", "observed", "mixed", "none")


@dataclass(frozen=True, slots=True)
class Candidate:
    """One internal provider capability able to satisfy a public capability."""

    provider: Any
    capability: Any
    public_id: str
    semantics: dict[str, Any]
    score: tuple[int, int, int]


def _candidate_trace_key(candidate: Candidate) -> str:
    return f"{candidate.provider.id}/{candidate.capability.id}"


def _provider_network_targets(provider: Any) -> list[dict[str, Any]]:
    """Return declared provider network targets without contacting the network."""
    getter = getattr(provider, "network_targets", None)
    if not callable(getter):
        return []
    try:
        targets = getter()
    except Exception:  # noqa: BLE001 - diagnostics must never change routing
        return []
    result: list[dict[str, Any]] = []
    for target in targets or ():
        result.append(
            {
                "purpose": getattr(target, "purpose", None),
                "scheme": getattr(target, "scheme", None),
                "host": getattr(target, "host", None),
                "port": getattr(target, "port", None),
                "target_type": getattr(target, "target_type", None),
                "required": getattr(target, "required", None),
                "capabilities": list(getattr(target, "capabilities", ()) or ()),
                "note": getattr(target, "note", None),
            }
        )
    return result


def _diagnostic_user_id(connection: websocket_api.ActiveConnection) -> str | None:
    """Return a stable user id for admin-only diagnostic fault scoping."""
    user = getattr(connection, "user", None)
    user_id = getattr(user, "id", None)
    return str(user_id) if user_id else None


def _consume_diagnostic_fault(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
) -> dict[str, Any] | None:
    """Consume one short-lived fault armed for this user's next resolve."""
    user_id = _diagnostic_user_id(connection)
    if user_id is None:
        return None
    store = hass.data.get(_DIAGNOSTIC_FAULTS_KEY)
    if not isinstance(store, dict):
        return None
    fault = store.pop(user_id, None)
    if not isinstance(fault, dict):
        return None
    armed_at = fault.get("armed_at")
    if not isinstance(armed_at, (int, float)):
        return None
    if monotonic() - float(armed_at) > _DIAGNOSTIC_FAULT_TTL_SECONDS:
        return None
    return fault


def _fault_matches_candidate(
    fault: dict[str, Any] | None,
    candidate: Candidate,
) -> bool:
    """Return whether an armed diagnostic fault targets this candidate."""
    if not fault:
        return False
    return (
        fault.get("provider_id") == candidate.provider.id
        and fault.get("capability_id") == candidate.capability.id
    )


class CandidateUnavailable(Exception):
    """Expected provider/candidate non-availability for a consumer request."""

    def __init__(self, code: str, *, retryable: bool, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.message = message


def _entries(hass: HomeAssistant) -> list[Any]:
    """Return configured WeatherRouter entries without assuming one is ready."""
    return list(hass.config_entries.async_entries(DOMAIN))


def _runtime_state(hass: HomeAssistant) -> tuple[bool, dict[str, Any]]:
    """Return readiness plus persistent routing settings without raising."""
    entries = _entries(hass)
    if not entries:
        return False, {
            "router_enabled": False,
            "enabled_domains": set(),
            "enabled_providers": set(),
            "status": "not_configured",
        }

    entry = entries[0]
    runtime = getattr(entry, "runtime_data", None)
    ready = runtime is not None
    if runtime is not None and callable(getattr(runtime, "routing_settings", None)):
        raw = runtime.routing_settings()
        return ready, {
            "router_enabled": bool(raw["router_enabled"]),
            "enabled_domains": set(raw["enabled_domains"]),
            "enabled_providers": set(raw["enabled_providers"]),
            "status": "ready" if ready else "loading",
        }

    options = entry.options
    return ready, {
        "router_enabled": bool(options.get(CONF_ROUTER_ENABLED, True)),
        "enabled_domains": set(options.get(CONF_ENABLED_DOMAINS, ())),
        "enabled_providers": set(options.get(CONF_ENABLED_PROVIDERS, ())),
        "status": "ready" if ready else "loading",
    }


def _load_mapping_sync() -> dict[str, Any]:
    """Load the shipped base map plus validated local extension contributions."""
    payload = json.loads(_CONSUMER_MAP_PATH.read_text(encoding="utf-8"))
    payload = merge_extension_capability_map(payload)
    if payload.get("schema") != "weather_router.consumer.capability_map.draft.v1":
        raise ValueError("consumer capability map has unexpected schema")
    if payload.get("contract_version") != CONSUMER_CONTRACT_VERSION:
        raise ValueError("consumer capability map has incompatible contract version")
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        raise ValueError("consumer capability map providers must be an object")

    resource_contract = payload.get("capability_resource_types")
    if not isinstance(resource_contract, dict):
        raise ValueError("consumer capability map needs capability_resource_types")
    if resource_contract.get("schema") != "weather_router.consumer.capability_resource_types.v1":
        raise ValueError("consumer capability resource types have unexpected schema")
    declared_allowed = resource_contract.get("allowed_resource_types")
    if not isinstance(declared_allowed, list) or set(declared_allowed) != _RESOURCE_TYPES:
        raise ValueError("consumer capability resource types have invalid allowed set")
    resource_providers = resource_contract.get("providers")
    if not isinstance(resource_providers, dict):
        raise ValueError("consumer capability resource types providers must be an object")
    if not set(resource_providers).issubset(set(providers)):
        raise ValueError("consumer capability resource types reference unknown providers")
    for provider_id, resource_map in resource_providers.items():
        provider_map = providers.get(provider_id)
        if not isinstance(provider_map, dict) or not isinstance(resource_map, dict):
            raise ValueError("consumer capability resource type provider map is invalid")
        if set(resource_map) != set(provider_map):
            raise ValueError(
                f"consumer capability resource type coverage mismatch for {provider_id}"
            )
        for internal_id, resource_type in resource_map.items():
            if resource_type not in _RESOURCE_TYPES:
                raise ValueError(
                    f"consumer capability resource type invalid for {provider_id}/{internal_id}"
                )

    physical_contract = payload.get("capability_physical_semantics")
    if not isinstance(physical_contract, dict):
        raise ValueError("consumer capability map needs capability_physical_semantics")
    if physical_contract.get("schema") != "weather_router.consumer.capability_physical_semantics.v1":
        raise ValueError("consumer capability physical semantics have unexpected schema")
    if set(physical_contract.get("unit_sources", [])) != {
        "provider_capability",
        "not_applicable",
    }:
        raise ValueError("consumer capability physical semantics have invalid unit sources")
    physical_providers = physical_contract.get("providers")
    if not isinstance(physical_providers, dict):
        raise ValueError("consumer capability physical semantics providers must be an object")
    if not set(physical_providers).issubset(set(providers)):
        raise ValueError("consumer capability physical semantics reference unknown providers")
    for provider_id, physical_map in physical_providers.items():
        provider_map = providers.get(provider_id)
        if not isinstance(provider_map, dict) or not isinstance(physical_map, dict):
            raise ValueError("consumer capability physical semantics provider map is invalid")
        if set(physical_map) != set(provider_map):
            raise ValueError(
                f"consumer capability physical semantics coverage mismatch for {provider_id}"
            )
        for internal_id, metadata in physical_map.items():
            if not isinstance(metadata, dict):
                raise ValueError(
                    f"consumer capability physical semantics invalid for {provider_id}/{internal_id}"
                )
            numeric = metadata.get("numeric")
            quantity = metadata.get("quantity")
            unit_source = metadata.get("unit_source")
            if not isinstance(numeric, bool):
                raise ValueError(
                    f"consumer capability physical semantics need numeric for {provider_id}/{internal_id}"
                )
            if numeric:
                if not isinstance(quantity, str) or not quantity:
                    raise ValueError(
                        f"consumer numeric capability needs quantity for {provider_id}/{internal_id}"
                    )
                if unit_source != "provider_capability":
                    raise ValueError(
                        f"consumer numeric capability needs provider unit source for {provider_id}/{internal_id}"
                    )
            else:
                if quantity is not None or unit_source != "not_applicable":
                    raise ValueError(
                        f"consumer non-numeric capability semantics invalid for {provider_id}/{internal_id}"
                    )

    source_contract = payload.get("capability_source_semantics")
    if not isinstance(source_contract, dict):
        raise ValueError("consumer capability map needs capability_source_semantics")
    if source_contract.get("schema") != "weather_router.consumer.capability_source_semantics.v1":
        raise ValueError("consumer capability source semantics have unexpected schema")
    source_providers = source_contract.get("providers")
    if not isinstance(source_providers, dict):
        raise ValueError("consumer capability source semantics providers must be an object")
    if not set(source_providers).issubset(set(providers)):
        raise ValueError("consumer capability source semantics reference unknown providers")
    for provider_id, source_map in source_providers.items():
        provider_map = providers.get(provider_id)
        if not isinstance(provider_map, dict) or not isinstance(source_map, dict):
            raise ValueError("consumer capability source semantics provider map is invalid")
        if set(source_map) != set(provider_map):
            raise ValueError(
                f"consumer capability source semantics coverage mismatch for {provider_id}"
            )
        for internal_id, metadata in source_map.items():
            if not isinstance(metadata, dict):
                raise ValueError(
                    f"consumer capability source semantics invalid for {provider_id}/{internal_id}"
                )
            for field in ("data_origin", "measurement_method"):
                value = metadata.get(field)
                if not isinstance(value, str) or not value or value == "unspecified":
                    raise ValueError(
                        f"consumer capability source semantics need {field} for "
                        f"{provider_id}/{internal_id}"
                    )

    observation_contract = payload.get("capability_observation_semantics")
    if not isinstance(observation_contract, dict):
        raise ValueError("consumer capability map needs capability_observation_semantics")
    if observation_contract.get("schema") != "weather_router.consumer.capability_observation_semantics.v1":
        raise ValueError("consumer capability observation semantics have unexpected schema")
    allowed_observation_kinds = observation_contract.get("allowed_observation_kinds")
    if not isinstance(allowed_observation_kinds, list) or not allowed_observation_kinds:
        raise ValueError("consumer capability observation semantics need allowed kinds")
    allowed_observation_kind_set = set(allowed_observation_kinds)
    observation_providers = observation_contract.get("providers")
    if not isinstance(observation_providers, dict):
        raise ValueError("consumer capability observation semantics providers must be an object")
    if not set(observation_providers).issubset(set(providers)):
        raise ValueError("consumer capability observation semantics reference unknown providers")
    for provider_id, observation_map in observation_providers.items():
        provider_map = providers.get(provider_id)
        if not isinstance(provider_map, dict) or not isinstance(observation_map, dict):
            raise ValueError("consumer capability observation semantics provider map is invalid")
        if set(observation_map) != set(provider_map):
            raise ValueError(
                f"consumer capability observation semantics coverage mismatch for {provider_id}"
            )
        for internal_id, metadata in observation_map.items():
            if not isinstance(metadata, dict):
                raise ValueError(
                    f"consumer capability observation semantics invalid for {provider_id}/{internal_id}"
                )
            kind = metadata.get("observation_kind")
            if not isinstance(kind, str) or kind not in allowed_observation_kind_set:
                raise ValueError(
                    f"consumer capability observation kind invalid for {provider_id}/{internal_id}"
                )

    validate_time_semantics_contract(payload, providers)

    coverage_contract = payload.get("capability_coverage_semantics")
    if not isinstance(coverage_contract, dict):
        raise ValueError("consumer capability map needs capability_coverage_semantics")
    if coverage_contract.get("schema") != "weather_router.consumer.capability_coverage_semantics.v1":
        raise ValueError("consumer capability coverage semantics have unexpected schema")
    coverage_providers = coverage_contract.get("providers")
    if not isinstance(coverage_providers, dict):
        raise ValueError("consumer capability coverage semantics providers must be an object")
    if not set(coverage_providers).issubset(set(providers)):
        raise ValueError("consumer capability coverage semantics reference unknown providers")
    allowed_scopes = set(coverage_contract.get("coverage_scopes", []))
    allowed_evidence = set(coverage_contract.get("coverage_evidence", []))
    allowed_authorities = set(coverage_contract.get("routing_authorities", []))
    allowed_spaces = set(coverage_contract.get("coordinate_spaces", []))
    for provider_id, coverage_map in coverage_providers.items():
        provider_map = providers.get(provider_id)
        if not isinstance(provider_map, dict) or not isinstance(coverage_map, dict):
            raise ValueError("consumer capability coverage semantics provider map is invalid")
        if set(coverage_map) != set(provider_map):
            raise ValueError(
                f"consumer capability coverage semantics coverage mismatch for {provider_id}"
            )
        for internal_id, metadata in coverage_map.items():
            if not isinstance(metadata, dict):
                raise ValueError(
                    f"consumer capability coverage semantics invalid for {provider_id}/{internal_id}"
                )
            if metadata.get("coverage_scope") not in allowed_scopes:
                raise ValueError(
                    f"consumer capability coverage scope invalid for {provider_id}/{internal_id}"
                )
            if metadata.get("coverage_evidence") not in allowed_evidence:
                raise ValueError(
                    f"consumer capability coverage evidence invalid for {provider_id}/{internal_id}"
                )
            if metadata.get("routing_authority") not in allowed_authorities:
                raise ValueError(
                    f"consumer capability coverage routing authority invalid for {provider_id}/{internal_id}"
                )
            if metadata.get("coordinate_space") not in allowed_spaces:
                raise ValueError(
                    f"consumer capability coordinate space invalid for {provider_id}/{internal_id}"
                )
            if metadata.get("endpoint_reachability_is_coverage") is not False:
                raise ValueError(
                    f"endpoint reachability must never be coverage evidence for {provider_id}/{internal_id}"
                )

    candidate_semantics = payload.get("candidate_semantics", {})
    if isinstance(candidate_semantics, dict):
        for candidate_key, semantic in candidate_semantics.items():
            if not isinstance(candidate_key, str) or "/" not in candidate_key:
                continue
            provider_id, internal_id = candidate_key.split("/", 1)
            physical = (
                physical_providers.get(provider_id, {}).get(internal_id)
                if isinstance(physical_providers.get(provider_id), dict)
                else None
            )
            if not isinstance(semantic, dict) or not isinstance(physical, dict):
                continue
            explicit_quantity = semantic.get("quantity")
            if (
                isinstance(explicit_quantity, str)
                and explicit_quantity
                and physical.get("numeric") is True
                and physical.get("quantity") != explicit_quantity
            ):
                raise ValueError(
                    f"candidate quantity drift for {provider_id}/{internal_id}: "
                    f"map={explicit_quantity!r}, normalized={physical.get('quantity')!r}"
                )
            source_semantic = (
                source_providers.get(provider_id, {}).get(internal_id)
                if isinstance(source_providers.get(provider_id), dict)
                else None
            )
            if isinstance(source_semantic, dict):
                for field in ("data_origin", "measurement_method"):
                    explicit_value = semantic.get(field)
                    if (
                        isinstance(explicit_value, str)
                        and explicit_value
                        and source_semantic.get(field) != explicit_value
                    ):
                        raise ValueError(
                            f"candidate {field} drift for {provider_id}/{internal_id}: "
                            f"map={explicit_value!r}, "
                            f"normalized={source_semantic.get(field)!r}"
                        )
            observation_semantic = (
                observation_providers.get(provider_id, {}).get(internal_id)
                if isinstance(observation_providers.get(provider_id), dict)
                else None
            )
            explicit_observation_kind = semantic.get("observation_kind")
            if (
                isinstance(explicit_observation_kind, str)
                and explicit_observation_kind
                and isinstance(observation_semantic, dict)
                and observation_semantic.get("observation_kind") != explicit_observation_kind
            ):
                raise ValueError(
                    f"candidate observation_kind drift for {provider_id}/{internal_id}: "
                    f"map={explicit_observation_kind!r}, "
                    f"normalized={observation_semantic.get('observation_kind')!r}"
                )

    phenomena = payload.get("phenomena", {})
    if not isinstance(phenomena, dict):
        raise ValueError("consumer capability map phenomena must be an object")
    for phenomenon_id, metadata in phenomena.items():
        if not isinstance(phenomenon_id, str) or not phenomenon_id or not isinstance(metadata, dict):
            raise ValueError("consumer capability map contains invalid phenomenon metadata")
        if not isinstance(metadata.get("name"), str) or not metadata["name"].strip():
            raise ValueError("consumer capability map phenomenon needs a display name")

    public_capabilities = payload.get("public_capabilities", {})
    if not isinstance(public_capabilities, dict):
        raise ValueError("consumer capability map public_capabilities must be an object")
    for public_id, metadata in public_capabilities.items():
        if not _PUBLIC_ID_RE.fullmatch(public_id) or not isinstance(metadata, dict):
            raise ValueError("consumer capability map contains invalid public metadata")
        if metadata.get("strategy", "single") not in {"single", "aggregate"}:
            raise ValueError("consumer capability map contains invalid strategy")
        family = metadata.get("family")
        if not isinstance(family, str) or not family:
            raise ValueError("consumer capability map public capability needs a family")
        capability_phenomena = metadata.get("phenomena", [])
        if (
            not isinstance(capability_phenomena, list)
            or any(item not in phenomena for item in capability_phenomena)
        ):
            raise ValueError("consumer capability map contains unknown phenomena")
        declared_resource_types = metadata.get("resource_types")
        if declared_resource_types is not None and (
            not isinstance(declared_resource_types, list)
            or not declared_resource_types
            or len(set(declared_resource_types)) != len(declared_resource_types)
            or any(item not in _RESOURCE_TYPES for item in declared_resource_types)
        ):
            raise ValueError("consumer capability map contains invalid resource_types")
        intent_contract = metadata.get("intent_contract")
        if intent_contract is not None:
            if not isinstance(intent_contract, dict):
                raise ValueError("consumer capability intent_contract must be an object")
            if intent_contract.get("resource_type") not in {
                "value",
                "raster_tile",
                "hazard_feed",
                "event_feed",
                "image_sequence",
                "live_stream",
                "planetary_tile",
                "data_file",
            }:
                raise ValueError("consumer capability intent_contract has invalid resource_type")
            if not isinstance(intent_contract.get("render_interchangeable"), bool):
                raise ValueError("consumer capability intent_contract needs render_interchangeable")
            if not isinstance(intent_contract.get("numeric_interchangeable"), bool):
                raise ValueError("consumer capability intent_contract needs numeric_interchangeable")
            semantic_fields = intent_contract.get("semantic_fields", [])
            if (
                not isinstance(semantic_fields, list)
                or any(not isinstance(item, str) or not item for item in semantic_fields)
            ):
                raise ValueError("consumer capability intent_contract has invalid semantic_fields")
    return payload


async def _async_mapping(hass: HomeAssistant) -> dict[str, Any]:
    return await hass.async_add_executor_job(_load_mapping_sync)


@lru_cache(maxsize=1)
def _load_hazard_types_sync() -> dict[str, Any]:
    """Load and minimally validate the public hazard event taxonomy."""
    payload = json.loads(_HAZARD_TYPES_PATH.read_text(encoding="utf-8"))
    if payload.get("schema") != "weather_router.consumer.hazard_event_types.v1":
        raise ValueError("consumer hazard taxonomy has unexpected schema")
    if payload.get("contract_version") != CONSUMER_CONTRACT_VERSION:
        raise ValueError("consumer hazard taxonomy has incompatible contract version")

    groups = payload.get("groups", {})
    if not isinstance(groups, dict):
        raise ValueError("consumer hazard taxonomy groups must be an object")
    for group_id, metadata in groups.items():
        if (
            not isinstance(group_id, str)
            or not group_id
            or not isinstance(metadata, dict)
            or not isinstance(metadata.get("name"), str)
            or not isinstance(metadata.get("domain"), str)
        ):
            raise ValueError("consumer hazard taxonomy contains invalid group metadata")

    hazard_types = payload.get("hazard_types")
    if not isinstance(hazard_types, dict) or not hazard_types:
        raise ValueError("consumer hazard taxonomy needs hazard types")
    for hazard_type, metadata in hazard_types.items():
        if (
            not isinstance(hazard_type, str)
            or not hazard_type
            or not isinstance(metadata, dict)
            or not isinstance(metadata.get("name"), str)
            or not isinstance(metadata.get("group"), str)
        ):
            raise ValueError("consumer hazard taxonomy contains invalid hazard metadata")

    severities = payload.get("severities")
    if not isinstance(severities, list) or not severities:
        raise ValueError("consumer hazard taxonomy needs severities")
    for item in severities:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not isinstance(item.get("name"), str)
        ):
            raise ValueError("consumer hazard taxonomy contains invalid severity metadata")
    return payload


async def _async_hazard_types(hass: HomeAssistant) -> dict[str, Any]:
    return await hass.async_add_executor_job(_load_hazard_types_sync)


def _consumer_profiles(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Return configured Consumer API profiles without exposing admin configuration."""
    entries = _entries(hass)
    if not entries:
        return {}
    entry = entries[0]
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


def _profile_for_request(
    hass: HomeAssistant,
    msg: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve one optional profile without making it mandatory for old consumers."""
    profile_id = msg.get("profile_id")
    if profile_id is None:
        return None, None
    if not isinstance(profile_id, str) or not PROFILE_ID_RE.fullmatch(profile_id):
        raise CandidateUnavailable(
            "profile_not_available",
            retryable=False,
            message="Das angeforderte Consumer-Profil ist ungültig oder nicht vorhanden.",
        )
    profile = _consumer_profiles(hass).get(profile_id)
    if profile is None or not profile.get("enabled", False):
        raise CandidateUnavailable(
            "profile_not_available",
            retryable=False,
            message="Das angeforderte Consumer-Profil ist nicht verfügbar.",
        )
    return profile_id, profile


async def _async_providers(hass: HomeAssistant) -> dict[str, Any]:
    return await hass.async_add_executor_job(provider_catalog)


def _provider_capability_map(provider: Any) -> dict[str, Any]:
    return {item.id: item for item in provider.capabilities()}


def _validate_mapping_against_providers(
    providers: dict[str, Any],
    mapping: dict[str, Any],
) -> None:
    """Fail closed when the shipped public map no longer matches provider contracts."""
    mapped = mapping["providers"]
    if not set(providers).issubset(set(mapped)):
        missing = sorted(set(providers) - set(mapped))
        raise ValueError(
            f"consumer capability map provider mismatch: missing={missing}"
        )

    mapped_public_ids = {
        public_id
        for provider_map in mapped.values()
        if isinstance(provider_map, dict)
        for public_ids in provider_map.values()
        if isinstance(public_ids, list)
        for public_id in public_ids
        if isinstance(public_id, str)
    }
    public_metadata = mapping.get("public_capabilities", {})
    if set(public_metadata) != mapped_public_ids:
        missing = sorted(mapped_public_ids - set(public_metadata))
        extra = sorted(set(public_metadata) - mapped_public_ids)
        raise ValueError(
            f"consumer public capability metadata mismatch: missing={missing}, extra={extra}"
        )

    resource_contract = mapping.get("capability_resource_types", {})
    resource_providers = (
        resource_contract.get("providers", {})
        if isinstance(resource_contract, dict)
        else {}
    )
    coverage_contract = mapping.get("capability_coverage_semantics", {})
    coverage_providers = (
        coverage_contract.get("providers", {})
        if isinstance(coverage_contract, dict)
        else {}
    )
    runtime_public_resource_types: dict[str, set[str]] = {}

    for provider_id, provider in providers.items():
        internal = _provider_capability_map(provider)
        provider_map = mapped.get(provider_id)
        if not isinstance(provider_map, dict):
            raise ValueError(f"consumer capability map missing provider {provider_id}")

        if set(provider_map) != set(internal):
            missing = sorted(set(internal) - set(provider_map))
            extra = sorted(set(provider_map) - set(internal))
            raise ValueError(
                f"consumer capability map mismatch for {provider_id}: "
                f"missing={missing}, extra={extra}"
            )

        static_resource_map = resource_providers.get(provider_id)
        if static_resource_map is not None:
            if not isinstance(static_resource_map, dict) or set(static_resource_map) != set(internal):
                raise ValueError(
                    f"consumer capability resource type mismatch for {provider_id}"
                )
            for internal_id, capability in internal.items():
                runtime_resource_type = getattr(capability, "render_mode", None)
                if static_resource_map.get(internal_id) != runtime_resource_type:
                    raise ValueError(
                        f"consumer capability resource type drift for "
                        f"{provider_id}/{internal_id}: "
                        f"map={static_resource_map.get(internal_id)!r}, "
                        f"runtime={runtime_resource_type!r}"
                    )

        static_coverage_map = coverage_providers.get(provider_id)
        if isinstance(static_coverage_map, dict):
            for internal_id, capability in internal.items():
                coverage_meta = static_coverage_map.get(internal_id, {})
                if coverage_meta.get("routing_authority") == "hard":
                    getter = getattr(provider, "async_get_coverage", None)
                    if not callable(getter):
                        raise ValueError(
                            f"hard coverage contract has no machine coverage provider for "
                            f"{provider_id}/{internal_id}"
                        )
                    if coverage_meta.get("coverage_evidence") != "machine_readable_runtime":
                        raise ValueError(
                            f"hard coverage contract needs machine-readable evidence for "
                            f"{provider_id}/{internal_id}"
                        )
                if coverage_meta.get("routing_authority") == "context_filter":
                    if capability.render_mode not in {"hazard_feed", "event_feed"}:
                        raise ValueError(
                            f"context-filter coverage requires event resource for "
                            f"{provider_id}/{internal_id}"
                        )

        provider_domains = set(getattr(provider, "router_domains", ("weather",)))
        for internal_id, public_ids in provider_map.items():
            if not isinstance(public_ids, list) or not public_ids:
                raise ValueError(
                    f"consumer capability map has no public ids for {provider_id}/{internal_id}"
                )
            for public_id in public_ids:
                if not isinstance(public_id, str) or not _PUBLIC_ID_RE.fullmatch(public_id):
                    raise ValueError(
                        f"consumer capability map has invalid public id {public_id!r}"
                    )
                domain = public_id.split(".", 1)[0]
                if domain not in ROUTER_DOMAINS:
                    raise ValueError(
                        f"consumer capability map has unknown domain {domain!r}"
                    )
                if domain not in provider_domains:
                    raise ValueError(
                        f"consumer capability map maps {provider_id}/{internal_id} "
                        f"outside provider domains"
                    )
                runtime_resource_type = getattr(internal[internal_id], "render_mode", None)
                runtime_public_resource_types.setdefault(public_id, set()).add(
                    runtime_resource_type
                )

    for public_id, runtime_types in runtime_public_resource_types.items():
        declared = public_metadata.get(public_id, {}).get("resource_types")
        if declared is None:
            # Local extensions may still rely on runtime-only metadata until their
            # own static contracts are versioned.
            continue
        if set(declared) != runtime_types:
            raise ValueError(
                f"consumer public capability resource type drift for {public_id}: "
                f"map={sorted(declared)!r}, runtime={sorted(runtime_types)!r}"
            )


def _validate_hazard_mapping(
    mapping: dict[str, Any],
    hazard_catalog: dict[str, Any],
) -> None:
    """Ensure every declared event filter type exists in the public taxonomy."""
    known = set(hazard_catalog["hazard_types"])
    for public_id, metadata in mapping.get("public_capabilities", {}).items():
        if not isinstance(metadata, dict):
            continue
        declared = metadata.get("hazard_types", [])
        if not isinstance(declared, list):
            raise ValueError(
                f"consumer capability {public_id} hazard_types must be a list"
            )
        unknown = sorted(
            item for item in declared
            if not isinstance(item, str) or item not in known
        )
        if unknown:
            raise ValueError(
                f"consumer capability {public_id} has unknown hazard types: {unknown}"
            )


def _candidate_enabled(
    state: dict[str, Any],
    provider: Any,
    public_id: str,
) -> tuple[bool, str | None]:
    """Apply hard global/domain/provider eligibility for a public capability."""
    if not state["router_enabled"]:
        return False, "router_disabled"

    domain = public_id.split(".", 1)[0]
    if domain not in state["enabled_domains"]:
        return False, "domain_disabled"

    if provider.id not in state["enabled_providers"]:
        return False, "provider_disabled"

    provider_domains = set(getattr(provider, "router_domains", ("weather",)))
    if domain not in provider_domains:
        return False, "domain_disabled"

    return True, None


def _candidates(
    providers: dict[str, Any],
    mapping: dict[str, Any],
    public_id: str,
    *,
    capability_maps: dict[str, dict[str, Any]] | None = None,
) -> list[Candidate]:
    """Return deterministic provider/capability candidates in registry order."""
    result: list[Candidate] = []
    mapped = mapping["providers"]
    for provider in providers.values():
        provider_map = mapped.get(provider.id)
        if not isinstance(provider_map, dict):
            continue
        capability_map = (
            capability_maps[provider.id]
            if capability_maps is not None
            else _provider_capability_map(provider)
        )
        for internal_id, public_ids in provider_map.items():
            if public_id not in public_ids:
                continue
            capability = capability_map.get(internal_id)
            if capability is not None:
                semantics = normalized_candidate_semantics(
                    mapping,
                    public_id,
                    provider.id,
                    capability.id,
                    source_class=getattr(capability, "source_class", None),
                    unit=getattr(capability, "unit", None),
                )
                result.append(
                    Candidate(
                        provider,
                        capability,
                        public_id,
                        semantics,
                        candidate_score(mapping, public_id, semantics),
                    )
                )
    result.sort(key=lambda candidate: candidate.score)
    return result


def _public_ids(mapping: dict[str, Any]) -> list[str]:
    values: set[str] = set()
    for provider_map in mapping["providers"].values():
        if not isinstance(provider_map, dict):
            continue
        for public_ids in provider_map.values():
            if not isinstance(public_ids, list):
                continue
            values.update(item for item in public_ids if isinstance(item, str))
    return sorted(values)


def _resolution_strategy(mapping: dict[str, Any], public_id: str) -> str:
    metadata = mapping.get("public_capabilities", {}).get(public_id, {})
    if not isinstance(metadata, dict):
        return "single"
    return str(metadata.get("strategy") or "single")


def _public_metadata(mapping: dict[str, Any], public_id: str) -> dict[str, Any]:
    metadata = mapping.get("public_capabilities", {}).get(public_id, {})
    return metadata if isinstance(metadata, dict) else {}


def _public_intent_contract(mapping: dict[str, Any], public_id: str) -> dict[str, Any] | None:
    """Return additive machine-readable intent guarantees for one public capability."""
    contract = _public_metadata(mapping, public_id).get("intent_contract")
    return dict(contract) if isinstance(contract, dict) else None


def _candidate_topics(
    mapping: dict[str, Any],
    candidate: Candidate,
) -> list[str]:
    """Return normalized topic ids for one base candidate."""
    contract = mapping.get("capability_topic_assignments", {})
    providers = contract.get("providers", {}) if isinstance(contract, dict) else {}
    provider_map = (
        providers.get(candidate.provider.id, {})
        if isinstance(providers, dict)
        else {}
    )
    metadata = (
        provider_map.get(candidate.capability.id)
        if isinstance(provider_map, dict)
        else None
    )
    topics = metadata.get("topics", []) if isinstance(metadata, dict) else []
    return [str(item) for item in topics if isinstance(item, str) and item]


def _candidate_time_semantics(
    mapping: dict[str, Any],
    candidate: Candidate,
) -> dict[str, Any] | None:
    """Return static time semantics for one base candidate when available."""
    contract = mapping.get("capability_time_semantics", {})
    providers = contract.get("providers", {}) if isinstance(contract, dict) else {}
    provider_map = (
        providers.get(candidate.provider.id, {})
        if isinstance(providers, dict)
        else {}
    )
    metadata = (
        provider_map.get(candidate.capability.id)
        if isinstance(provider_map, dict)
        else None
    )
    return dict(metadata) if isinstance(metadata, dict) else None


def _public_time_semantics(
    mapping: dict[str, Any],
    candidates: list[Candidate],
) -> dict[str, Any] | None:
    """Aggregate candidate time contracts without inventing shared values."""
    rows = [
        item
        for candidate in candidates
        if (item := _candidate_time_semantics(mapping, candidate)) is not None
    ]
    if not rows:
        return None
    fields = (
        "request_time_mode",
        "data_time",
        "valid_time",
        "forecast_reference_time",
        "interval_start",
        "interval_end",
        "accumulation_period",
        "frame_cadence",
        "freshness_policy",
    )
    return {
        "candidate_count": len(rows),
        **{
            field: sorted({str(row.get(field)) for row in rows})
            for field in fields
        },
    }


def _candidate_coverage_semantics(
    mapping: dict[str, Any],
    candidate: Candidate,
) -> dict[str, Any] | None:
    """Return static coverage semantics for one base candidate when available."""
    contract = mapping.get("capability_coverage_semantics", {})
    providers = contract.get("providers", {}) if isinstance(contract, dict) else {}
    provider_map = (
        providers.get(candidate.provider.id, {})
        if isinstance(providers, dict)
        else {}
    )
    metadata = (
        provider_map.get(candidate.capability.id)
        if isinstance(provider_map, dict)
        else None
    )
    return dict(metadata) if isinstance(metadata, dict) else None


def _public_coverage_semantics(
    mapping: dict[str, Any],
    candidates: list[Candidate],
) -> dict[str, Any] | None:
    """Aggregate candidate coverage semantics without treating reachability as coverage."""
    rows = [
        item
        for candidate in candidates
        if (item := _candidate_coverage_semantics(mapping, candidate)) is not None
    ]
    if not rows:
        return None
    fields = (
        "coverage_scope",
        "coverage_evidence",
        "routing_authority",
        "coordinate_space",
    )
    return {
        "candidate_count": len(rows),
        "endpoint_reachability_is_coverage": False,
        **{
            field: sorted({str(row.get(field)) for row in rows})
            for field in fields
        },
    }


def _machine_coverage_declared(candidate: Candidate) -> bool:
    """Return whether a raster candidate exposes machine-readable coverage."""
    getter = getattr(candidate.provider, "async_get_coverage", None)
    return callable(getter)


def _coverage_contract_allows(
    mapping: dict[str, Any],
    candidate: Candidate,
) -> tuple[bool, str | None]:
    """Apply optional public-intent coverage contract without changing special IDs."""
    if candidate.capability.render_mode != "raster_tile":
        return True, None
    policy = str(_public_metadata(mapping, candidate.public_id).get("coverage_policy") or "")
    if policy != "required":
        return True, None
    if _machine_coverage_declared(candidate):
        return True, None
    return False, "machine_coverage_required"


def _public_family(mapping: dict[str, Any], public_id: str) -> str:
    metadata = _public_metadata(mapping, public_id)
    family = metadata.get("family")
    if isinstance(family, str) and family:
        return family
    parts = public_id.split(".")
    return parts[1] if len(parts) > 1 else "general"


def _public_phenomena(mapping: dict[str, Any], public_id: str) -> list[str]:
    metadata = _public_metadata(mapping, public_id)
    values = metadata.get("phenomena", [])
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, str)]


def _public_hazard_types(mapping: dict[str, Any], public_id: str) -> list[str]:
    metadata = _public_metadata(mapping, public_id)
    values = metadata.get("hazard_types", [])
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, str)]


def _hazard_filter_options(
    mapping: dict[str, Any],
    hazard_catalog: dict[str, Any],
    public_id: str,
) -> dict[str, Any] | None:
    allowed = _public_hazard_types(mapping, public_id)
    if not allowed:
        return None

    taxonomy = hazard_catalog["hazard_types"]
    groups = hazard_catalog.get("groups", {})
    used_groups = {
        taxonomy[hazard_type]["group"]
        for hazard_type in allowed
        if hazard_type in taxonomy
    }
    result = {
        "hazard_types": [
            {
                "id": hazard_type,
                "name": taxonomy[hazard_type]["name"],
                "group": taxonomy[hazard_type]["group"],
            }
            for hazard_type in allowed
            if hazard_type in taxonomy
        ],
        "groups": [
            {
                "id": group_id,
                "name": groups[group_id]["name"],
                "domain": groups[group_id]["domain"],
            }
            for group_id in sorted(used_groups)
            if group_id in groups
        ],
        "severities": list(hazard_catalog["severities"]),
    }
    if (
        {"tornado", "waterspout", "hail", "windstorm", "downburst", "supercell"}.intersection(allowed)
        or public_id in _FLOOD_SEMANTIC_PUBLIC_IDS
    ):
        result["alert_stages"] = [
            "warning",
            "watch",
            "outlook",
            "statement",
            "unspecified",
        ]
    if {"tornado", "waterspout"}.intersection(allowed):
        result.update(
            {
                "hazard_match_scopes": [
                    "explicit_event",
                    "contextual_text",
                ],
                "tornado_semantic_classes": [
                    "official_tornado_alert_event",
                    "official_waterspout_alert_event",
                ],
            }
        )
    if "hail" in allowed:
        result.update(
            {
                "hail_match_scopes": [
                    "explicit_event",
                    "contextual_text",
                ],
                "hail_semantic_classes": [
                    "official_hail_alert_event",
                ],
            }
        )
    if {"windstorm", "downburst"}.intersection(allowed):
        result.update(
            {
                "wind_hazard_match_scopes": [
                    "explicit_event",
                    "contextual_text",
                ],
                "wind_hazard_semantic_classes": [
                    "official_wind_alert_event",
                    "official_downburst_alert_event",
                ],
            }
        )
    if "supercell" in allowed:
        result.update(
            {
                "supercell_match_scopes": [
                    "explicit_event",
                    "contextual_text",
                ],
                "supercell_semantic_classes": [
                    "official_supercell_alert_event",
                ],
            }
        )
    if public_id in _FLOOD_SEMANTIC_PUBLIC_IDS:
        result.update(
            {
                "flood_match_scopes": list(_FLOOD_MATCH_SCOPES),
                "flood_semantic_classes": list(_FLOOD_SEMANTIC_CLASSES),
            }
        )
    if public_id in _TROPICAL_SYSTEM_PUBLIC_IDS:
        result["tropical_system_classes"] = list(_TROPICAL_SYSTEM_CLASSES)
    if public_id in _TSUNAMI_SEMANTIC_PUBLIC_IDS:
        result["tsunami_semantic_classes"] = list(_TSUNAMI_SEMANTIC_CLASSES)
    if public_id in _TSUNAMI_ALERT_STAGE_PUBLIC_IDS:
        result["tsunami_alert_stages"] = list(_TSUNAMI_ALERT_STAGES)
    return result


def _phenomenon_catalog(mapping: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for phenomenon_id, metadata in mapping.get("phenomena", {}).items():
        if not isinstance(metadata, dict):
            continue
        name = metadata.get("name")
        if isinstance(name, str):
            result.append({"id": phenomenon_id, "name": name})
    return result


def _spatial_contexts(render_mode: str) -> list[str]:
    if render_mode == "value":
        return ["point"]
    if render_mode in {"hazard_feed", "event_feed"}:
        return ["global", "point", "bbox"]
    if render_mode == "raster_tile":
        return ["global", "point", "bbox"]
    return ["global"]


def _public_name(
    mapping: dict[str, Any],
    public_id: str,
    candidates: list[Candidate],
) -> str:
    """Return provider-neutral public display metadata when declared."""
    declared = _public_metadata(mapping, public_id).get("name")
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    if candidates:
        first = candidates[0].capability
        name = getattr(first, "name", None)
        if isinstance(name, str) and name.strip():
            return name.strip()
    return public_id.replace("_", " ").replace(".", " · ")


def _resource_implemented(candidate: Candidate) -> bool:
    mode = candidate.capability.render_mode
    if mode == "value":
        return callable(getattr(candidate.provider, "async_fetch_point", None))
    if mode == "hazard_feed":
        return callable(getattr(candidate.provider, "async_get_hazard_feed", None))
    if mode == "event_feed":
        return callable(getattr(candidate.provider, "async_get_event_feed", None))
    if mode == "data_file":
        return callable(getattr(candidate.provider, "async_get_data_file", None))
    if mode in {
        "raster_tile",
        "image_sequence",
        "live_stream",
        "planetary_tile",
    }:
        return callable(getattr(candidate.provider, "async_get_map_layer", None))
    return False


def _capability_catalog_row(
    state: dict[str, Any],
    mapping: dict[str, Any],
    hazard_catalog: dict[str, Any],
    candidates: list[Candidate],
    public_id: str,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resource_types = sorted({item.capability.render_mode for item in candidates})
    source_classes = sorted({item.capability.source_class for item in candidates})
    spatial = sorted({
        context
        for item in candidates
        for context in _spatial_contexts(item.capability.render_mode)
    })

    eligible = [
        item
        for item in candidates
        if _candidate_enabled(state, item.provider, public_id)[0]
        and profile_allows_provider(profile, item.provider.id)
        and profile_allows_candidate(profile, item.semantics)[0]
    ]
    resolvable = [item for item in eligible if _resource_implemented(item)]

    row = {
        "id": public_id,
        "domain": public_id.split(".", 1)[0],
        "family": _public_family(mapping, public_id),
        "phenomena": _public_phenomena(mapping, public_id),
        "name": _public_name(mapping, public_id, candidates),
        "enabled": bool(eligible),
        "available": bool(resolvable),
        "resource_types": resource_types,
        "spatial_contexts": spatial,
        # Phase-C prototype is intentionally conservative. Provider timelines may
        # contain history, but public at/range semantics are not frozen yet.
        "time_modes": ["latest"],
        "source_classes": source_classes,
        "description": (
            str(_public_metadata(mapping, public_id).get("description")).strip()
            if isinstance(_public_metadata(mapping, public_id).get("description"), str)
            and str(_public_metadata(mapping, public_id).get("description")).strip()
            else None
        ),
        "resolution_strategy": _resolution_strategy(mapping, public_id),
        "availability_basis": (
            "eligibility_only" if resolvable
            else "resource_resolution_pending" if eligible
            else "disabled"
        ),
    }
    time_semantics = _public_time_semantics(mapping, candidates)
    if time_semantics is not None:
        row["time_semantics"] = time_semantics
    coverage_semantics = _public_coverage_semantics(mapping, candidates)
    if coverage_semantics is not None:
        row["coverage_semantics"] = coverage_semantics
    intent_contract = _public_intent_contract(mapping, public_id)
    if intent_contract is not None:
        row["intent_contract"] = intent_contract
    event_filter_options = _hazard_filter_options(mapping, hazard_catalog, public_id)
    if event_filter_options is not None:
        row["event_filter_options"] = event_filter_options
    # Advertise the exact server-authorized event policy in existing catalog
    # responses. This is optional metadata, not a second event router.
    if len(row.get("resource_types") or []) == 1:
        resource = row["resource_types"][0]
        from .consumer_event_time_policy import time_class, _CLASSES, _MAX_RESULTS, _MAX_PAGES
        declared = time_class(public_id, resource)
        if declared is not None:
            limits = _CLASSES[declared]
            row["time_modes"].append("events_intersecting_window")
            row["event_time_options"] = {
                "mode": "events_intersecting_window",
                "class": declared,
                "max_window_days": limits["days"],
                "default_max_feed_update_age_seconds": limits["feed_seconds"],
                "max_feed_update_age_seconds": limits["feed_seconds"] * 4,
                "max_ongoing_update_age_seconds": limits["ongoing_seconds"],
                "max_results": _MAX_RESULTS,
                "default_page_size": _MAX_RESULTS,
                "max_pages": _MAX_PAGES,
                "include_ongoing_supported": limits["ongoing_seconds"] > 0,
            }
    return row


def _catalog_filter(raw: Any, mapping: dict[str, Any]) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise vol.Invalid("filter must be an object")

    allowed = {"domains", "families", "phenomena", "resource_types", "available_only"}
    unknown = set(raw) - allowed
    if unknown:
        raise vol.Invalid(f"unsupported catalog filter fields: {sorted(unknown)}")

    result: dict[str, Any] = {}
    known_phenomena = set(mapping.get("phenomena", {}))
    for key in ("domains", "families", "phenomena", "resource_types"):
        if key not in raw:
            continue
        values = raw[key]
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(item, str) and item for item in values)
        ):
            raise vol.Invalid(f"{key} must be a non-empty string list")
        unique = set(values)
        if key == "domains" and not unique.issubset(ROUTER_DOMAINS):
            raise vol.Invalid("filter contains unknown domains")
        if key == "phenomena" and not unique.issubset(known_phenomena):
            raise vol.Invalid("filter contains unknown phenomena")
        result[key] = unique

    if "available_only" in raw:
        if not isinstance(raw["available_only"], bool):
            raise vol.Invalid("available_only must be boolean")
        result["available_only"] = raw["available_only"]
    return result


def _catalog_row_matches(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    if filters.get("domains") and row["domain"] not in filters["domains"]:
        return False
    if filters.get("families") and row["family"] not in filters["families"]:
        return False
    if filters.get("phenomena") and not set(row["phenomena"]).intersection(filters["phenomena"]):
        return False
    if filters.get("resource_types") and not set(row["resource_types"]).intersection(filters["resource_types"]):
        return False
    if filters.get("available_only") and not row["available"]:
        return False
    return True


def _catalog_filter_options(rows: list[dict[str, Any]], mapping: dict[str, Any]) -> dict[str, Any]:
    used_phenomena = {
        item
        for row in rows
        for item in row.get("phenomena", [])
    }
    return {
        "domains": sorted({row["domain"] for row in rows}),
        "families": sorted({row["family"] for row in rows}),
        "phenomena": [
            item
            for item in _phenomenon_catalog(mapping)
            if item["id"] in used_phenomena
        ],
        "resource_types": sorted({
            item
            for row in rows
            for item in row.get("resource_types", [])
        }),
    }


def _validate_contract_version(msg: dict[str, Any]) -> bool:
    return msg.get("contract_version") == CONSUMER_CONTRACT_VERSION


def _coordinate(value: Any, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise vol.Invalid("invalid coordinate")
    number = float(value)
    if not isfinite(number) or not minimum <= number <= maximum:
        raise vol.Invalid("invalid coordinate")
    return number


def _context(msg: dict[str, Any]) -> dict[str, Any]:
    raw = msg.get("context")
    if not isinstance(raw, dict):
        raise vol.Invalid("context must be an object")
    kind = raw.get("type")
    if kind == "global":
        if set(raw) != {"type"}:
            raise vol.Invalid("global context accepts only type")
        return {"type": "global"}
    if kind == "point":
        if set(raw) != {"type", "latitude", "longitude"}:
            raise vol.Invalid("point context contains unsupported fields")
        return {
            "type": "point",
            "latitude": _coordinate(raw.get("latitude"), -90.0, 90.0),
            "longitude": _coordinate(raw.get("longitude"), -180.0, 180.0),
        }
    if kind == "bbox":
        if set(raw) != {"type", "west", "south", "east", "north"}:
            raise vol.Invalid("bbox context contains unsupported fields")
        west = _coordinate(raw.get("west"), -180.0, 180.0)
        south = _coordinate(raw.get("south"), -90.0, 90.0)
        east = _coordinate(raw.get("east"), -180.0, 180.0)
        north = _coordinate(raw.get("north"), -90.0, 90.0)
        if south > north:
            raise vol.Invalid("bbox south must not exceed north")
        return {
            "type": "bbox",
            "west": west,
            "south": south,
            "east": east,
            "north": north,
        }
    raise vol.Invalid("unsupported context type")


def _time_context(msg: dict[str, Any]) -> dict[str, Any]:
    raw = msg.get("time")
    if not isinstance(raw, dict):
        raise vol.Invalid("time must be an object")
    mode = raw.get("mode")
    if mode == "latest" and set(raw) != {"mode"}:
        raise vol.Invalid("latest time context accepts only mode")
    if mode == "events_intersecting_window":
        # Validate timestamps, class and bounds after the verified catalog has
        # determined the actual feed type for this public capability.
        return dict(raw)
    if mode != "latest":
        raise CandidateUnavailable(
            "requirements_not_met",
            retryable=False,
            message="Unbekannter oder für diese Capability nicht erlaubter Zeitmodus.",
        )
    return {"mode": "latest"}


def _requirements(msg: dict[str, Any]) -> dict[str, Any]:
    raw = msg.get("requirements")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise vol.Invalid("requirements must be an object")

    allowed = {
        "resource_types",
        "source_classes",
        "max_age_seconds",
        "timeline_required",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise vol.Invalid(f"unsupported requirements: {sorted(unknown)}")

    result: dict[str, Any] = {}
    if "resource_types" in raw:
        values = raw["resource_types"]
        if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
            raise vol.Invalid("resource_types must be a non-empty string list")
        result["resource_types"] = set(values)
    if "source_classes" in raw:
        values = raw["source_classes"]
        if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
            raise vol.Invalid("source_classes must be a non-empty string list")
        result["source_classes"] = set(values)
    if "max_age_seconds" in raw:
        value = raw["max_age_seconds"]
        if isinstance(value, bool):
            raise vol.Invalid("max_age_seconds must be an integer")
        value = int(value)
        if value < 0:
            raise vol.Invalid("max_age_seconds must be >= 0")
        result["max_age_seconds"] = value
    if "timeline_required" in raw:
        if not isinstance(raw["timeline_required"], bool):
            raise vol.Invalid("timeline_required must be boolean")
        result["timeline_required"] = raw["timeline_required"]
    return result


def _event_filter(
    msg: dict[str, Any],
    hazard_catalog: dict[str, Any],
) -> dict[str, set[str]]:
    raw = msg.get("event_filter")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise vol.Invalid("event_filter must be an object")

    allowed = {
        "hazard_types",
        "severities",
        "alert_stages",
        "hazard_match_scopes",
        "tornado_semantic_classes",
        "hail_match_scopes",
        "hail_semantic_classes",
        "wind_hazard_match_scopes",
        "wind_hazard_semantic_classes",
        "supercell_match_scopes",
        "supercell_semantic_classes",
        "flood_match_scopes",
        "flood_semantic_classes",
        "tropical_system_classes",
        "tsunami_semantic_classes",
        "tsunami_alert_stages",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise vol.Invalid(f"unsupported event_filter fields: {sorted(unknown)}")

    result: dict[str, set[str]] = {}
    if "hazard_types" in raw:
        values = raw["hazard_types"]
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(item, str) and item for item in values)
        ):
            raise vol.Invalid("hazard_types must be a non-empty string list")
        known = set(hazard_catalog["hazard_types"])
        requested = set(values)
        if not requested.issubset(known):
            raise vol.Invalid(
                f"unknown hazard_types: {sorted(requested - known)}"
            )
        result["hazard_types"] = requested

    if "severities" in raw:
        values = raw["severities"]
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(item, str) and item for item in values)
        ):
            raise vol.Invalid("severities must be a non-empty string list")
        known = {
            item["id"]
            for item in hazard_catalog["severities"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        requested = set(values)
        if not requested.issubset(known):
            raise vol.Invalid(
                f"unknown severities: {sorted(requested - known)}"
            )
        result["severities"] = requested

    fixed_options = {
        "alert_stages": {
            "warning",
            "watch",
            "outlook",
            "statement",
            "unspecified",
        },
        "hazard_match_scopes": {
            "explicit_event",
            "contextual_text",
        },
        "tornado_semantic_classes": {
            "official_tornado_alert_event",
            "official_waterspout_alert_event",
        },
        "hail_match_scopes": {
            "explicit_event",
            "contextual_text",
        },
        "hail_semantic_classes": {
            "official_hail_alert_event",
        },
        "wind_hazard_match_scopes": {
            "explicit_event",
            "contextual_text",
        },
        "wind_hazard_semantic_classes": {
            "official_wind_alert_event",
            "official_downburst_alert_event",
        },
        "supercell_match_scopes": {
            "explicit_event",
            "contextual_text",
        },
        "supercell_semantic_classes": {
            "official_supercell_alert_event",
        },
        "flood_match_scopes": set(_FLOOD_MATCH_SCOPES),
        "flood_semantic_classes": set(_FLOOD_SEMANTIC_CLASSES),
        "tropical_system_classes": set(_TROPICAL_SYSTEM_CLASSES),
        "tsunami_semantic_classes": set(_TSUNAMI_SEMANTIC_CLASSES),
        "tsunami_alert_stages": set(_TSUNAMI_ALERT_STAGES),
    }
    for field, known in fixed_options.items():
        if field not in raw:
            continue
        values = raw[field]
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(item, str) and item for item in values)
        ):
            raise vol.Invalid(f"{field} must be a non-empty string list")
        requested = set(values)
        if not requested.issubset(known):
            raise vol.Invalid(
                f"unknown {field}: {sorted(requested - known)}"
            )
        result[field] = requested

    return result


def _validate_event_filter_for_capability(
    mapping: dict[str, Any],
    public_id: str,
    event_filter: dict[str, set[str]],
) -> None:
    if not event_filter:
        return

    allowed_types = set(_public_hazard_types(mapping, public_id))
    if not allowed_types:
        raise CandidateUnavailable(
            "requirements_not_met",
            retryable=False,
            message="Event-Filter sind nur für Gefahrenfeeds verfügbar.",
        )

    requested_types = event_filter.get("hazard_types")
    if requested_types and not requested_types.issubset(allowed_types):
        raise CandidateUnavailable(
            "requirements_not_met",
            retryable=False,
            message=(
                "Mindestens ein angeforderter Ereignistyp gehört nicht zur "
                "gewählten öffentlichen Gefahren-Capability."
            ),
        )

    tornado_dimensions = {
        "hazard_match_scopes",
        "tornado_semantic_classes",
    }
    if tornado_dimensions.intersection(event_filter) and not {
        "tornado",
        "waterspout",
    }.intersection(allowed_types):
        raise CandidateUnavailable(
            "requirements_not_met",
            retryable=False,
            message=(
                "Tornado-spezifische Event-Filter sind nur für öffentliche "
                "Gefahren-Capabilities mit Tornado-/Wasserhosen-Semantik verfügbar."
            ),
        )

    hail_dimensions = {
        "hail_match_scopes",
        "hail_semantic_classes",
    }
    if hail_dimensions.intersection(event_filter) and "hail" not in allowed_types:
        raise CandidateUnavailable(
            "requirements_not_met",
            retryable=False,
            message=(
                "Hagel-spezifische Event-Filter sind nur für öffentliche "
                "Gefahren-Capabilities mit Hagel-Semantik verfügbar."
            ),
        )

    wind_hazard_dimensions = {
        "wind_hazard_match_scopes",
        "wind_hazard_semantic_classes",
    }
    if wind_hazard_dimensions.intersection(event_filter) and not {
        "windstorm",
        "downburst",
    }.intersection(allowed_types):
        raise CandidateUnavailable(
            "requirements_not_met",
            retryable=False,
            message=(
                "Windgefahren-spezifische Event-Filter sind nur für öffentliche "
                "Gefahren-Capabilities mit Starkwind-/Downburst-Semantik verfügbar."
            ),
        )

    supercell_dimensions = {
        "supercell_match_scopes",
        "supercell_semantic_classes",
    }
    if supercell_dimensions.intersection(event_filter) and "supercell" not in allowed_types:
        raise CandidateUnavailable(
            "requirements_not_met",
            retryable=False,
            message=(
                "Superzellen-spezifische Event-Filter sind nur für öffentliche "
                "Gefahren-Capabilities mit Superzellen-Semantik verfügbar."
            ),
        )

    flood_dimensions = {
        "flood_match_scopes",
        "flood_semantic_classes",
    }
    if (
        flood_dimensions.intersection(event_filter)
        and public_id not in _FLOOD_SEMANTIC_PUBLIC_IDS
    ):
        raise CandidateUnavailable(
            "requirements_not_met",
            retryable=False,
            message=(
                "Hochwasser-spezifische Event-Filter sind nur für die "
                "freigegebenen amtlichen Warning-Capabilities verfügbar."
            ),
        )

    if (
        "tropical_system_classes" in event_filter
        and public_id not in _TROPICAL_SYSTEM_PUBLIC_IDS
    ):
        raise CandidateUnavailable(
            "requirements_not_met",
            retryable=False,
            message=(
                "Tropensystem-spezifische Event-Filter sind nur für die "
                "freigegebenen Tropical-Cyclone-Capabilities verfügbar."
            ),
        )

    if (
        "tsunami_semantic_classes" in event_filter
        and public_id not in _TSUNAMI_SEMANTIC_PUBLIC_IDS
    ):
        raise CandidateUnavailable(
            "requirements_not_met",
            retryable=False,
            message="Tsunami-Semantikfilter sind für diese Capability nicht freigegeben.",
        )
    if (
        "tsunami_alert_stages" in event_filter
        and public_id not in _TSUNAMI_ALERT_STAGE_PUBLIC_IDS
    ):
        raise CandidateUnavailable(
            "requirements_not_met",
            retryable=False,
            message="Tsunami-Warnstufenfilter sind nur für natural_hazards.tsunami.warnings verfügbar.",
        )


def _serialized_event_filter(
    event_filter: dict[str, set[str]],
) -> dict[str, list[str]]:
    return {
        key: sorted(values)
        for key, values in event_filter.items()
        if values
    }


def _event_matches_filter(
    event: dict[str, Any],
    event_filter: dict[str, set[str]],
) -> bool:
    hazard_types = event_filter.get("hazard_types")
    if hazard_types and str(event.get("hazard_type") or "") not in hazard_types:
        return False

    severities = event_filter.get("severities")
    severity = str(event.get("severity") or "unknown").strip().casefold() or "unknown"
    if severities and severity not in severities:
        return False

    requested_flood_classes = event_filter.get("flood_semantic_classes")
    requested_flood_scopes = event_filter.get("flood_match_scopes")
    if requested_flood_classes or requested_flood_scopes:
        flood_items = [
            item
            for item in event.get("flood_semantics", [])
            if isinstance(item, dict)
            and isinstance(item.get("semantic_class"), str)
            and isinstance(item.get("match_scope"), str)
        ]
        if requested_flood_classes and requested_flood_scopes:
            if not any(
                item["semantic_class"] in requested_flood_classes
                and item["match_scope"] in requested_flood_scopes
                for item in flood_items
            ):
                return False
        elif requested_flood_classes:
            if not any(
                item["semantic_class"] in requested_flood_classes
                for item in flood_items
            ):
                return False
        elif requested_flood_scopes and not any(
            item["match_scope"] in requested_flood_scopes
            for item in flood_items
        ):
            return False

    requested_tropical_classes = event_filter.get("tropical_system_classes")
    if requested_tropical_classes:
        tropical_system = event.get("tropical_system")
        system_class = (
            tropical_system.get("system_class")
            if isinstance(tropical_system, dict)
            else None
        )
        if system_class not in requested_tropical_classes:
            return False

    tsunami_meta = event.get("tsunami_semantics")
    requested_tsunami_classes = event_filter.get("tsunami_semantic_classes")
    if requested_tsunami_classes:
        semantic_class = tsunami_meta.get("semantic_class") if isinstance(tsunami_meta, dict) else None
        if semantic_class not in requested_tsunami_classes:
            return False
    requested_tsunami_stages = event_filter.get("tsunami_alert_stages")
    if requested_tsunami_stages:
        tsunami_stage = tsunami_meta.get("alert_stage") if isinstance(tsunami_meta, dict) else None
        if tsunami_stage not in requested_tsunami_stages:
            return False

    field_filters = {
        "alert_stages": "alert_stage",
        "hazard_match_scopes": "hazard_match_scope",
        "tornado_semantic_classes": "tornado_semantic_class",
        "hail_match_scopes": "hail_match_scope",
        "hail_semantic_classes": "hail_semantic_class",
        "wind_hazard_match_scopes": "wind_hazard_match_scope",
        "wind_hazard_semantic_classes": "wind_hazard_semantic_class",
        "supercell_match_scopes": "supercell_match_scope",
        "supercell_semantic_classes": "supercell_semantic_class",
    }
    for filter_name, event_field in field_filters.items():
        requested = event_filter.get(filter_name)
        if requested and str(event.get(event_field) or "") not in requested:
            return False

    return True


def _tsunami_geometry_match(
    geometry: dict[str, Any] | None,
    context: dict[str, Any],
) -> bool | None:
    """Return True/False only when real event geometry can decide relevance."""
    if not isinstance(geometry, dict):
        return None
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Point":
        if (
            not isinstance(coordinates, (list, tuple))
            or len(coordinates) < 2
            or not isinstance(coordinates[0], (int, float))
            or not isinstance(coordinates[1], (int, float))
        ):
            return None
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
        if context["type"] == "point":
            return (
                abs(longitude - float(context["longitude"])) <= 1e-9
                and abs(latitude - float(context["latitude"])) <= 1e-9
            )
        if context["type"] == "bbox":
            west, south, east, north = (
                float(context["west"]), float(context["south"]),
                float(context["east"]), float(context["north"]),
            )
            longitude_match = west <= longitude <= east if west <= east else longitude >= west or longitude <= east
            return longitude_match and south <= latitude <= north
        return None
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        return None
    if context["type"] == "point":
        return point_in_geometry(geometry, float(context["longitude"]), float(context["latitude"]))
    if context["type"] == "bbox":
        return geometry_intersects_bbox_strict(
            geometry,
            (float(context["west"]), float(context["south"]), float(context["east"]), float(context["north"])),
        )
    return None


def _apply_tsunami_spatial_filter(
    payload: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Best-effort point/bbox filtering without inventing coverage."""
    if context["type"] == "global":
        return payload
    result = dict(payload)
    kept: list[dict[str, Any]] = []
    matched = nonmatched = unknown = 0
    for raw in payload.get("events", []):
        if not isinstance(raw, dict):
            continue
        event = dict(raw)
        if not isinstance(event.get("tsunami_semantics"), dict):
            kept.append(event)
            continue
        decision = _tsunami_geometry_match(event.get("geometry"), context)
        if decision is True:
            event["spatial_relevance"] = "matched_geometry"
            matched += 1
            kept.append(event)
        elif decision is False:
            nonmatched += 1
        else:
            event["spatial_relevance"] = "unknown_geometry"
            unknown += 1
            kept.append(event)
    result["events"] = kept
    result["event_count"] = len(kept)
    result["spatial_filter"] = {
        "mode": "event_geometry_best_effort",
        "context_type": context["type"],
        "geometry_matched_count": matched,
        "geometry_nonmatched_count": nonmatched,
        "unknown_geometry_count": unknown,
        "complete": unknown == 0,
    }
    return result


def _filter_hazard_payload(
    payload: dict[str, Any],
    event_filter: dict[str, set[str]],
) -> dict[str, Any]:
    if not event_filter:
        return payload

    raw_events = [
        item for item in payload.get("events", [])
        if isinstance(item, dict)
    ]
    events = [
        item for item in raw_events
        if _event_matches_filter(item, event_filter)
    ]
    result = dict(payload)
    result["events"] = events
    result["event_count"] = len(events)
    result["unfiltered_event_count"] = len(raw_events)
    result["event_filter"] = _serialized_event_filter(event_filter)
    result["filtered"] = True
    return result


def _context_supported(candidate: Candidate, context: dict[str, Any]) -> bool:
    if (
        (candidate.public_id in _CIVIL_PROTECTION_PUBLIC_IDS
         or candidate.public_id in _SECURITY_PUBLIC_IDS)
        and context["type"] == "point"
    ):
        return False
    return context["type"] in _spatial_contexts(candidate.capability.render_mode)


def _requirements_match(candidate: Candidate, requirements: dict[str, Any]) -> bool:
    if (
        "resource_types" in requirements
        and candidate.capability.render_mode not in requirements["resource_types"]
    ):
        return False
    if (
        "source_classes" in requirements
        and candidate.capability.source_class not in requirements["source_classes"]
    ):
        return False
    return True


def _safe_public_url(value: Any) -> str | None:
    """Return a public http(s) URL only when no credential-like query/userinfo exists."""
    if not isinstance(value, str) or not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return None
    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.casefold() in _SENSITIVE_QUERY_KEYS:
            return None
    return value


def _iso_time(value: Any, *, epoch_unit: str | None = None) -> str | None:
    """Explicit UTC instant only; reject unspecified numeric units and naive text."""
    from .time_normalization import iso_instant, epoch_instant
    if type(value) in (int, float):
        return epoch_instant(value, unit=epoch_unit) if epoch_unit else None
    return iso_instant(value)



def _age_seconds(data_time: str | None) -> float | None:
    from .time_normalization import iso_instant
    normalized = iso_instant(data_time)
    if normalized is None:
        return None
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())



def _timeline_frames(raw: Any, *, url_field: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for frame in raw:
        if not isinstance(frame, dict):
            continue
        frame_url = _safe_public_url(frame.get(url_field))
        frame_time = _iso_time(frame.get("time"))
        if frame_url is None or frame_time is None:
            continue
        result.append({"time": frame_time, "url": frame_url})
    return result


def _provider_attribution(provider: Any, result: dict[str, Any]) -> str | None:
    direct = result.get("attribution")
    if isinstance(direct, str):
        return direct
    info_getter = getattr(provider, "provider_info", None)
    if callable(info_getter):
        info = info_getter()
        attribution = getattr(info, "attribution", None)
        if isinstance(attribution, str):
            return attribution
    return None


def _provenance(candidate: Candidate, result: dict[str, Any]) -> dict[str, Any]:
    info_getter = getattr(candidate.provider, "provider_info", None)
    limitations: list[str] = []
    if callable(info_getter):
        info = info_getter()
        limitations = list(getattr(info, "limitations", ()) or ())
    data: dict[str, Any] = {
        "mode": "single",
        "provider_id": candidate.provider.id,
        "provider_name": candidate.provider.name,
        "source_class": str(result.get("source_class") or candidate.capability.source_class),
        "data_semantics": dict(candidate.semantics),
        "attribution": _provider_attribution(candidate.provider, result),
        "source_semantics": result.get("source_semantics"),
        "coverage": getattr(candidate.capability, "coverage", None),
        "limitations": limitations,
    }
    machine_coverage = normalize_coverage(result.get("machine_coverage"))
    if machine_coverage is not None:
        data["spatial_coverage"] = machine_coverage
    return data


def _source_provenance(candidate: Candidate, result: dict[str, Any]) -> dict[str, Any]:
    data = _provenance(candidate, result)
    data.pop("mode", None)
    return data


def _aggregate_provenance(sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "mode": "aggregate",
        "sources": sources,
    }


def _normalize_raster(result: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    def _source_time(field_path: str, raw_value: Any) -> str | None:
        if raw_value is None:
            return None
        # Lazy fuer explizit zeitlose Raster (z.B. Referenzdaten).
        from .time_normalization import normalize_provider_time
        return normalize_provider_time(
            str(result.get("provider") or ""),
            str(result.get("capability") or ""),
            field_path, raw_value,
            provider_metadata=result.get("provider_metadata"),
        ).iso
    tile_url = _safe_public_url(result.get("tile_url"))
    if tile_url is None:
        raise CandidateUnavailable(
            "credentials_required",
            retryable=False,
            message="Der Layer enthält keine secret-freie direkte Kachel-URL.",
        )
    payload: dict[str, Any] = {
        "tile_url": tile_url,
        "tile_size": int(result.get("tile_size") or 256),
        "max_zoom": float(result.get("max_zoom") if result.get("max_zoom") is not None else 18),
    }
    if result.get("min_zoom") is not None:
        payload["min_zoom"] = float(result["min_zoom"])
    if result.get("default_opacity") is not None:
        payload["default_opacity"] = float(result["default_opacity"])
    payload["attribution"] = result.get("attribution")

    # GBIF species, observation-window, and licensing information must survive
    # the generic raster normalizer. Expose only an explicit public-data allowlist
    # for this provider: never forward arbitrary upstream metadata or URLs.
    if result.get("provider") == "gbif_biodiversity":
        raw_metadata = result.get("provider_metadata")
        if isinstance(raw_metadata, dict):
            public_metadata: dict[str, Any] = {}
            string_fields = (
                "service",
                "taxonomy",
                "semantics",
                "scientific_name_requested",
                "scientific_name_matched",
                "taxon_key",
                "taxon_rank",
                "taxon_status",
                "match_type",
                "group",
                "group_name",
                "quality_filter",
                "warning",
            )
            for field in string_fields:
                value = raw_metadata.get(field)
                if isinstance(value, str) and value and len(value) <= 1024:
                    public_metadata[field] = value
            for field in ("from_year", "to_year", "match_confidence"):
                value = raw_metadata.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    public_metadata[field] = value
            for field in ("population_density", "risk_probability"):
                value = raw_metadata.get(field)
                if isinstance(value, bool):
                    public_metadata[field] = value
            terms_url = _safe_public_url(raw_metadata.get("data_user_agreement"))
            if terms_url is not None:
                public_metadata["data_user_agreement"] = terms_url
            if public_metadata:
                payload["provider_metadata"] = public_metadata

    # Preserve provider-neutral legend metadata through Consumer V1. Only
    # secret-free public URLs are exposed; consumers never need to know which
    # provider produced the raster.
    legend = result.get("legend")
    if isinstance(legend, dict):
        legend_url = _safe_public_url(legend.get("url"))
        legend_title = legend.get("title")
        normalized_legend: dict[str, Any] = {}
        if legend_url is not None:
            normalized_legend["url"] = legend_url
        if isinstance(legend_title, str) and legend_title.strip():
            normalized_legend["title"] = legend_title.strip()
        legend_style = legend.get("style")
        if isinstance(legend_style, str) and legend_style.strip():
            normalized_legend["style"] = legend_style.strip()
        if normalized_legend:
            payload["legend"] = normalized_legend

    timeline = result.get("timeline")
    if isinstance(timeline, dict):
        frames = []
        for frame in timeline.get("frames", []):
            if not isinstance(frame, dict):
                continue
            url = _safe_public_url(frame.get("tile_url"))
            # Der deklarative UTC-Quellenvertrag ist die EINZIGE Zeitgrenze.
            # Fehlende/mehrdeutige Rohzeit darf niemals als frisch erscheinen.
            time_value = _source_time("timeline.frames[].time", frame.get("time"))
            if url is None or time_value is None:
                continue
            item = {"time": time_value, "tile_url": url}
            frame_kind = frame.get("kind")
            if isinstance(frame_kind, str) and frame_kind.strip():
                item["kind"] = frame_kind.strip()
            frames.append(item)
        normalized_timeline: dict[str, Any] = {
            "mode": "frames",
            "default": (
                str(timeline.get("default"))
                if isinstance(timeline.get("default"), str)
                else "latest"
            ),
            "loop": bool(timeline.get("loop", True)),
            "frames": frames,
        }
        for index_field in ("default_index", "current_index"):
            value = timeline.get(index_field)
            if isinstance(value, int) and not isinstance(value, bool):
                normalized_timeline[index_field] = value
        payload["timeline"] = normalized_timeline

    return payload, _source_time("frame_time", result.get("frame_time"))


def _validate_intent_resource_contract(
    mapping: dict[str, Any],
    public_id: str,
    candidate: Candidate,
    payload: dict[str, Any],
) -> None:
    """Validate additive public-intent guarantees without conflating numeric semantics."""
    contract = _public_intent_contract(mapping, public_id)
    if contract is None:
        return

    required_type = contract.get("resource_type")
    if isinstance(required_type, str) and candidate.capability.render_mode != required_type:
        raise CandidateUnavailable(
            "requirements_not_met",
            retryable=False,
            message="Der Candidate erfüllt den Resource-Typ des öffentlichen Intents nicht.",
        )

    semantic_fields = contract.get("semantic_fields", [])
    if isinstance(semantic_fields, list):
        for field in semantic_fields:
            if field == "unit":
                if field not in candidate.semantics:
                    raise CandidateUnavailable(
                        "requirements_not_met",
                        retryable=False,
                        message="Der Candidate deklariert das Unit-Feld des öffentlichen Intents nicht.",
                    )
                continue
            value = candidate.semantics.get(field)
            if not isinstance(value, str) or not value:
                raise CandidateUnavailable(
                    "requirements_not_met",
                    retryable=False,
                    message=f"Der Candidate deklariert die erforderliche Semantik {field!r} nicht.",
                )

    if contract.get("attribution") == "required":
        attribution = payload.get("attribution")
        if not isinstance(attribution, str) or not attribution.strip():
            raise CandidateUnavailable(
                "requirements_not_met",
                retryable=False,
                message="Der Candidate liefert keine erforderliche Attribution.",
            )

    if contract.get("legend") == "required":
        legend = payload.get("legend")
        if not isinstance(legend, dict):
            raise CandidateUnavailable(
                "requirements_not_met",
                retryable=False,
                message="Der Candidate liefert keine erforderliche Legende.",
            )
        legend_url = legend.get("url")
        if not isinstance(legend_url, str) or not legend_url:
            raise CandidateUnavailable(
                "requirements_not_met",
                retryable=False,
                message="Die Candidate-Legende besitzt keine öffentliche URL.",
            )


def _normalize_image_sequence(result: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    timeline = result.get("timeline")
    frames_raw = timeline.get("frames") if isinstance(timeline, dict) else None
    frames = _timeline_frames(frames_raw, url_field="image_url")
    if not frames:
        raise CandidateUnavailable(
            "temporarily_unavailable",
            retryable=True,
            message="Die Bildfolge enthält derzeit keine nutzbaren Frames.",
        )
    payload = {
        "georeferenced": bool(result.get("extent") or result.get("georeferenced", False)),
        "frames": frames,
        "default_index": (
            int(timeline.get("default_index"))
            if isinstance(timeline, dict) and isinstance(timeline.get("default_index"), int)
            else len(frames) - 1
        ),
        "loop": bool(timeline.get("loop", True)) if isinstance(timeline, dict) else True,
    }
    return payload, frames[-1]["time"]


def _normalize_live_stream(result: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    stream = result.get("stream")
    if not isinstance(stream, dict):
        raise CandidateUnavailable(
            "temporarily_unavailable",
            retryable=True,
            message="Der Livestream-Descriptor fehlt.",
        )
    url = _safe_public_url(stream.get("embed_url") or stream.get("url"))
    if url is None:
        raise CandidateUnavailable(
            "credentials_required",
            retryable=False,
            message="Der Livestream enthält keine secret-freie direkte URL.",
        )
    return {
        "url": url,
        "transport": "direct",
        "content_type": "text/html" if stream.get("kind") == "iframe" else None,
        "title": stream.get("title"),
        "attribution": result.get("attribution"),
    }, None


def _normalize_planetary_tile(result: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    planetary = result.get("planetary")
    if not isinstance(planetary, dict):
        raise CandidateUnavailable(
            "temporarily_unavailable",
            retryable=True,
            message="Der Planetenkachel-Descriptor fehlt.",
        )
    url = _safe_public_url(planetary.get("tile_url_template") or planetary.get("tile_url"))
    if url is None:
        raise CandidateUnavailable(
            "credentials_required",
            retryable=False,
            message="Die Planetenkachelquelle enthält keine secret-freie URL.",
        )
    payload = {
        "body": str(planetary.get("body") or "unknown"),
        "tile_url": url,
        "min_zoom": float(planetary.get("min_zoom") or 0),
        "max_zoom": float(planetary.get("max_zoom") or 0),
        "tile_size": int(planetary.get("tile_size") or 256),
        "crs": planetary.get("projection"),
        "attribution": result.get("attribution"),
    }
    return payload, None


def _normalize_event_feed(
    candidate: Candidate,
    result: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Normalize non-warning observation events without hazard semantics."""
    if result.get("available") is False:
        raise CandidateUnavailable(
            "temporarily_unavailable",
            retryable=True,
            message=str(result.get("reason") or "Die Ereignisquelle ist aktuell nicht verfügbar."),
        )

    events: list[dict[str, Any]] = []
    latest_time: str | None = None
    for raw in result.get("events", []):
        if not isinstance(raw, dict):
            continue
        event_id = str(raw.get("id") or "").strip()
        event_type = str(raw.get("event_type") or "").strip()
        observed_at = _iso_time(raw.get("observed_at"))
        if not event_id or not event_type or observed_at is None:
            continue
        if latest_time is None or observed_at > latest_time:
            latest_time = observed_at

        event = {
            "id": event_id,
            "event_type": event_type,
            "observed_at": observed_at,
            "latitude": raw.get("latitude"),
            "longitude": raw.get("longitude"),
            "distance_km": raw.get("distance_km"),
            "azimuth_deg": raw.get("azimuth_deg"),
            "source_distance_km": raw.get("source_distance_km"),
            "source_azimuth_deg": raw.get("source_azimuth_deg"),
            "status": raw.get("status"),
            "region": raw.get("region"),
            "source_semantics": str(
                result.get("source_semantics")
                or result.get("source_class")
                or candidate.capability.source_class
            ),
            "provenance": _source_provenance(candidate, result),
        }
        for optional_key in (
            "peak_current_ka",
            "multiplicity",
            "cloud_indicator",
            "lightning_type",
            "ellipse_major_km",
        ):
            if raw.get(optional_key) is not None:
                event[optional_key] = raw.get(optional_key)
        events.append(event)

    return {
        "events": events,
        "event_count": len(events),
        "window_seconds": result.get("window_seconds"),
    }, latest_time


def _generic_hazard_type_for_public_id(public_id: str) -> str:
    """Return the safest generic public hazard type for one capability domain."""
    domain = public_id.split(".", 1)[0]
    if domain == "weather":
        return "weather_warning"
    if domain == "civil_protection":
        return "civil_protection"
    if domain == "security":
        return "public_safety"
    if domain == "aviation":
        return "aviation_warning"
    return "natural_hazard"


def _normalize_hazard_feed(
    candidate: Candidate,
    result: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    if result.get("coverage_status") == "outside_coverage":
        raise CandidateUnavailable(
            "outside_coverage",
            retryable=False,
            message="Die angefragte Position liegt außerhalb der Providerabdeckung.",
        )

    events: list[dict[str, Any]] = []
    latest_time: str | None = None
    for raw in result.get("events", []):
        if not isinstance(raw, dict):
            continue
        event_id = str(raw.get("id") or "").strip()
        provider_hazard_type = str(raw.get("hazard_type") or "").strip()
        if not event_id or not provider_hazard_type:
            continue

        known_hazard_types = _load_hazard_types_sync()["hazard_types"]
        hazard_type = (
            provider_hazard_type
            if provider_hazard_type in known_hazard_types
            else _generic_hazard_type_for_public_id(candidate.public_id)
        )
        headline = str(raw.get("headline") or raw.get("event") or provider_hazard_type).strip()
        if not headline:
            continue
        parameters = (
            dict(raw.get("parameters"))
            if isinstance(raw.get("parameters"), dict)
            else {}
        )
        if hazard_type != provider_hazard_type:
            parameters["provider_hazard_type"] = provider_hazard_type
            parameters["hazard_type_fallback"] = hazard_type
        effective = _iso_time(raw.get("effective") or raw.get("sent") or raw.get("onset"))
        if effective and (latest_time is None or effective > latest_time):
            latest_time = effective
        event = {
            "id": event_id,
            "hazard_type": hazard_type,
            "event": raw.get("event"),
            "headline": headline,
            "source_semantics": str(
                raw.get("source_semantics")
                or result.get("source_semantics")
                or result.get("source_class")
                or candidate.capability.source_class
            ),
            "severity": raw.get("severity"),
            "urgency": raw.get("urgency"),
            "certainty": raw.get("certainty"),
            "status": raw.get("status"),
            "lifecycle_status": raw.get("lifecycle_status"),
            "message_type": raw.get("message_type"),
            "started_at": _iso_time(raw.get("started_at")),
            "occurred_at": _iso_time(raw.get("occurred_at")),
            "resolved_at": _iso_time(raw.get("resolved_at")),
            "last_updated_at": _iso_time(raw.get("last_updated_at")),
            "published_at": _iso_time(raw.get("published_at")),
            "valid_from": _iso_time(raw.get("valid_from")),
            "valid_until": _iso_time(raw.get("valid_until")),
            "sent": _iso_time(raw.get("sent")),
            "effective": effective,
            "onset": _iso_time(raw.get("onset")),
            "expires": _iso_time(raw.get("expires")),
            "ends": _iso_time(raw.get("ends")),
            "area_desc": raw.get("area_desc"),
            "geometry": raw.get("geometry") if isinstance(raw.get("geometry"), dict) else None,
            "description": raw.get("description"),
            "instruction": raw.get("instruction"),
            "response": raw.get("response"),
            "parameters": parameters,
            "provenance": _source_provenance(candidate, result),
        }
        for semantic_key in (
            "tornado_semantic_class",
            "alert_stage",
            "hazard_match_scope",
            "hail_semantic_class",
            "hail_match_scope",
            "wind_hazard_semantic_class",
            "wind_hazard_match_scope",
            "supercell_semantic_class",
            "supercell_match_scope",
        ):
            if raw.get(semantic_key) is not None:
                event[semantic_key] = raw.get(semantic_key)

        raw_flood_semantics = raw.get("flood_semantics")
        if isinstance(raw_flood_semantics, list):
            normalized_flood_semantics = []
            for item in raw_flood_semantics:
                if not isinstance(item, dict):
                    continue
                semantic_class = item.get("semantic_class")
                match_scope = item.get("match_scope")
                if (
                    semantic_class in _FLOOD_SEMANTIC_CLASSES
                    and match_scope in _FLOOD_MATCH_SCOPES
                ):
                    normalized_flood_semantics.append(
                        {
                            "semantic_class": semantic_class,
                            "match_scope": match_scope,
                        }
                    )
            if normalized_flood_semantics:
                event["flood_semantics"] = normalized_flood_semantics

        raw_tropical_system = raw.get("tropical_system")
        if isinstance(raw_tropical_system, dict):
            system_class = raw_tropical_system.get("system_class")
            if system_class in _TROPICAL_SYSTEM_CLASSES:
                tropical_system = {"system_class": system_class}
                source_classification = raw_tropical_system.get("source_classification")
                if isinstance(source_classification, str) and source_classification.strip():
                    tropical_system["source_classification"] = source_classification.strip()
                regional_term = raw_tropical_system.get("regional_term")
                if regional_term in _TROPICAL_REGIONAL_TERMS:
                    tropical_system["regional_term"] = regional_term
                classification_source = raw_tropical_system.get("classification_source")
                if classification_source in _TROPICAL_CLASSIFICATION_SOURCES:
                    tropical_system["classification_source"] = classification_source
                event["tropical_system"] = tropical_system


        raw_earthquake_semantics = raw.get("earthquake_semantics")
        if isinstance(raw_earthquake_semantics, dict):
            semantic_class = raw_earthquake_semantics.get("semantic_class")
            if semantic_class in _EARTHQUAKE_SEMANTIC_CLASSES:
                quake_meta: dict[str, Any] = {"semantic_class": semantic_class}
                catalog_selection = raw_earthquake_semantics.get("catalog_selection")
                if catalog_selection in _EARTHQUAKE_CATALOG_SELECTIONS:
                    quake_meta["catalog_selection"] = catalog_selection
                for field in (
                    "magnitude",
                    "depth_km",
                    "felt_reports",
                    "community_intensity_cdi",
                    "instrumental_intensity_mmi",
                    "significance",
                ):
                    value = raw_earthquake_semantics.get(field)
                    if (
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and isfinite(float(value))
                    ):
                        quake_meta[field] = value
                for field in (
                    "magnitude_type",
                    "pager_alert",
                    "source_status",
                    "catalog_updated",
                    "legacy_magnitude_display_band",
                ):
                    value = raw_earthquake_semantics.get(field)
                    if isinstance(value, str) and value.strip():
                        quake_meta[field] = value.strip()
                tsunami_flag = raw_earthquake_semantics.get("tsunami_flag")
                if isinstance(tsunami_flag, bool):
                    quake_meta["tsunami_flag"] = tsunami_flag
                event["earthquake_semantics"] = quake_meta


        raw_volcano_semantics = raw.get("volcano_semantics")
        if isinstance(raw_volcano_semantics, dict):
            semantic_class = raw_volcano_semantics.get("semantic_class")
            if semantic_class in _VOLCANO_SEMANTIC_CLASSES:
                volcano_meta: dict[str, Any] = {"semantic_class": semantic_class}
                for field in (
                    "report_type",
                    "aviation_color_code",
                    "volcano_alert_level",
                    "smithsonian_vnum",
                    "volcano_code",
                    "observatory",
                    "region",
                    "nvews_threat",
                    "notice_type",
                    "source_event_type",
                    "legacy_severity_band",
                ):
                    value = raw_volcano_semantics.get(field)
                    if isinstance(value, str) and value.strip():
                        volcano_meta[field] = value.strip()
                categories = raw_volcano_semantics.get("report_categories")
                if isinstance(categories, list):
                    normalized_categories = []
                    for value in categories:
                        if not isinstance(value, str):
                            continue
                        text_value = value.strip()
                        if text_value and text_value not in normalized_categories:
                            normalized_categories.append(text_value)
                    if normalized_categories:
                        volcano_meta["report_categories"] = normalized_categories
                event["volcano_semantics"] = volcano_meta

        raw_tsunami_semantics = raw.get("tsunami_semantics")
        if isinstance(raw_tsunami_semantics, dict):
            semantic_class = raw_tsunami_semantics.get("semantic_class")
            if semantic_class in _TSUNAMI_SEMANTIC_CLASSES:
                tsunami_meta: dict[str, Any] = {"semantic_class": semantic_class}
                alert_stage = raw_tsunami_semantics.get("alert_stage")
                if alert_stage in _TSUNAMI_ALERT_STAGES:
                    tsunami_meta["alert_stage"] = alert_stage
                source_alert_level = raw_tsunami_semantics.get("source_alert_level")
                if isinstance(source_alert_level, str) and source_alert_level.strip():
                    tsunami_meta["source_alert_level"] = source_alert_level.strip()
                active_threat = raw_tsunami_semantics.get("active_threat")
                if isinstance(active_threat, bool):
                    tsunami_meta["active_threat"] = active_threat
                wave_evidence = raw_tsunami_semantics.get("wave_evidence")
                if wave_evidence in _TSUNAMI_WAVE_EVIDENCE:
                    tsunami_meta["wave_evidence"] = wave_evidence
                event["tsunami_semantics"] = tsunami_meta

        web_url = _safe_public_url(raw.get("web_url"))
        if web_url is not None:
            event["web_url"] = web_url
        events.append(event)

    payload = {
        "events": events,
        "event_count": len(events),
    }
    for key in (
        "unfiltered_event_count",
        "coverage_status",
        "geometry_status",
        "spatial_filter",
        "provider_metadata",
        "provider_revision",
    ):
        if result.get(key) is not None:
            payload[key] = result.get(key)
    return payload, latest_time


async def _raster_machine_coverage(
    hass: HomeAssistant,
    candidate: Candidate,
    context: dict[str, Any],
    trace: RoutingTrace | None = None,
) -> dict[str, Any] | None:
    """Check optional machine coverage and trace the decision without changing it."""
    key = _candidate_trace_key(candidate)
    getter = getattr(candidate.provider, "async_get_coverage", None)
    if not callable(getter):
        if trace is not None:
            trace.candidate_coverage(
                key,
                {
                    "machine_coverage": False,
                    "support": "not_declared",
                    "final_status": "not_checked_backward_compatible",
                    "routing_match": None,
                },
            )
            trace.candidate_check(
                key,
                "coverage",
                True,
                "not_declared_backward_compatible",
            )
        return None

    try:
        if trace is not None:
            trace.candidate_provider_contact(key)
        raw = await getter(hass, candidate.capability.id)
    except CandidateUnavailable:
        raise
    except Exception as err:
        if trace is not None:
            error_message = redact_text(str(err))
            trace.candidate_coverage(
                key,
                {
                    "machine_coverage": True,
                    "valid": False,
                    "final_status": "coverage_error",
                    "error_type": type(err).__name__,
                    "error_message": error_message,
                },
            )
            trace.candidate_check(key, "coverage", False, "temporarily_unavailable")
            trace.add_error(
                stage="coverage",
                code="coverage_error",
                message=error_message,
                exception_type=type(err).__name__,
            )
        raise CandidateUnavailable(
            "temporarily_unavailable",
            retryable=True,
            message="Maschinenlesbare Coverage-Metadaten des Providers sind aktuell nicht verfügbar.",
        ) from err

    coverage = normalize_coverage(raw)
    if coverage is None:
        if trace is not None:
            trace.candidate_coverage(
                key,
                {
                    "machine_coverage": True,
                    "valid": False,
                    "final_status": "invalid_coverage",
                },
            )
            trace.candidate_check(key, "coverage", False, "temporarily_unavailable")
        raise CandidateUnavailable(
            "temporarily_unavailable",
            retryable=True,
            message="Der Rasterprovider lieferte keine gültige maschinenlesbare Coverage.",
        )

    diagnostic = coverage_diagnostics(coverage, context)
    if trace is not None:
        trace.candidate_coverage(key, diagnostic)
        trace.candidate_check(
            key,
            "coverage",
            bool(diagnostic.get("routing_match")),
            diagnostic.get("final_status"),
        )
    if not coverage_matches_context(coverage, context):
        raise CandidateUnavailable(
            "outside_coverage",
            retryable=False,
            message="Der angefragte räumliche Kontext liegt außerhalb der Rasterabdeckung.",
        )
    return coverage


async def _resolve_candidate(
    hass: HomeAssistant,
    candidate: Candidate,
    context: dict[str, Any],
    requirements: dict[str, Any],
    event_filter: dict[str, set[str]],
    trace: RoutingTrace | None = None,
    diagnostic_fault: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    mode = candidate.capability.render_mode
    key = _candidate_trace_key(candidate)

    if mode == "value":
        if context["type"] != "point":
            raise CandidateUnavailable(
                "requirements_not_met",
                retryable=False,
                message="Punktwerte benötigen context.type=point.",
            )
        fetch = getattr(candidate.provider, "async_fetch_point", None)
        if not callable(fetch):
            raise CandidateUnavailable(
                "temporarily_unavailable",
                retryable=True,
                message="Der Punktdatenadapter ist nicht verfügbar.",
            )
        if trace is not None:
            trace.candidate_provider_contact(key)
        result = await fetch(
            hass,
            context["latitude"],
            context["longitude"],
            [candidate.capability.id],
        )
        if not isinstance(result, dict):
            raise ValueError("point provider returned no object")
        if result.get("coverage_status") == "outside_coverage":
            raise CandidateUnavailable(
                "outside_coverage",
                retryable=False,
                message=str(result.get("reason") or "Punkt liegt außerhalb der Providerabdeckung."),
            )
        if result.get("available") is False:
            if result.get("unavailable_code") == "temporarily_unavailable":
                raise CandidateUnavailable(
                    "temporarily_unavailable",
                    retryable=True,
                    message=str(
                        result.get("reason")
                        or "Der Provider besitzt aktuell keine nutzbaren Punktdaten."
                    ),
                )
            raise CandidateUnavailable(
                "outside_coverage",
                retryable=False,
                message=str(result.get("reason") or "Punkt liegt außerhalb der Providerabdeckung."),
            )
        values = result.get("values")
        entry = values.get(candidate.capability.id) if isinstance(values, dict) else None
        if not isinstance(entry, dict):
            raise CandidateUnavailable(
                "temporarily_unavailable",
                retryable=True,
                message="Der Provider lieferte keinen Wert für die angefragte Capability.",
            )
        data_time = _iso_time(result.get("data_time"))
        try:
            value = normalize_shared_wind_value(candidate.public_id, entry)
            value = normalize_snowfall_value(
                candidate.public_id,
                value,
                result,
            )
            value = normalize_visibility_value(candidate.public_id, value)
            value = normalize_uv_index_value(candidate.public_id, value)
            value = normalize_lightning_value(candidate.public_id, value)
            value = normalize_thunder_value(candidate.public_id, value)
        except ValueError as err:
            raise CandidateUnavailable(
                "requirements_not_met",
                retryable=False,
                message=str(err),
            ) from err
        value["data_time"] = data_time
        payload = {"values": {candidate.public_id: value}}
        return payload, result, data_time

    if mode == "event_feed":
        fetch = getattr(candidate.provider, "async_get_event_feed", None)
        if not callable(fetch):
            raise CandidateUnavailable(
                "temporarily_unavailable",
                retryable=True,
                message="Der Ereignisfeedadapter ist nicht verfügbar.",
            )
        kwargs: dict[str, Any] = {"limit": 1000}
        if context["type"] == "point":
            kwargs["latitude"] = context["latitude"]
            kwargs["longitude"] = context["longitude"]
        elif context["type"] == "bbox":
            kwargs["bbox"] = (
                context["west"],
                context["south"],
                context["east"],
                context["north"],
            )
        if trace is not None:
            trace.candidate_provider_contact(key)
        result = await fetch(hass, candidate.capability.id, **kwargs)
        if not isinstance(result, dict):
            raise ValueError("event provider returned no object")
        payload, data_time = _normalize_event_feed(candidate, result)
        try:
            payload = apply_lightning_resource_semantics(candidate.public_id, payload)
        except ValueError as err:
            raise CandidateUnavailable(
                "requirements_not_met",
                retryable=False,
                message=str(err),
            ) from err
        return payload, result, data_time

    if mode == "hazard_feed":
        if (
            candidate.public_id in _AVIATION_PUBLIC_IDS
            and context["type"] == "point"
        ):
            raise CandidateUnavailable(
                "requirements_not_met",
                retryable=False,
                message=(
                    "Aviation-Point-Abfragen benötigen eine explizite räumliche "
                    "Point-in-Geometry- oder Distanzsemantik. Bitte BBOX oder Global verwenden."
                ),
            )

        if (
            candidate.public_id in _EARTHQUAKE_PUBLIC_IDS
            and context["type"] == "point"
        ):
            raise CandidateUnavailable(
                "requirements_not_met",
                retryable=False,
                message=(
                    "Erdbeben-Point-Abfragen benötigen eine explizite Distanz-/"
                    "Radiussemantik. Bitte BBOX oder Global verwenden."
                ),
            )

        if (
            candidate.public_id in _VOLCANO_PUBLIC_IDS
            and context["type"] == "point"
        ):
            raise CandidateUnavailable(
                "requirements_not_met",
                retryable=False,
                message=(
                    "Vulkan-Point-Abfragen benötigen eine explizite Distanz-/"
                    "Radiussemantik. Bitte BBOX oder Global verwenden."
                ),
            )
        fetch = getattr(candidate.provider, "async_get_hazard_feed", None)
        if not callable(fetch):
            raise CandidateUnavailable(
                "temporarily_unavailable",
                retryable=True,
                message="Der Gefahrenfeedadapter ist nicht verfügbar.",
            )
        kwargs: dict[str, Any] = {"limit": 1000}
        if context["type"] == "point":
            kwargs["latitude"] = context["latitude"]
            kwargs["longitude"] = context["longitude"]
        elif context["type"] == "bbox":
            kwargs["bbox"] = (
                context["west"],
                context["south"],
                context["east"],
                context["north"],
            )
        if trace is not None:
            trace.candidate_provider_contact(key)
        result = await fetch(hass, candidate.capability.id, **kwargs)
        if not isinstance(result, dict):
            raise ValueError("hazard provider returned no object")
        payload, data_time = _normalize_hazard_feed(candidate, result)
        if (
            candidate.public_id in _EARTHQUAKE_PUBLIC_IDS
            and context["type"] == "bbox"
        ):
            quake_events = [
                item for item in payload.get("events", [])
                if isinstance(item, dict)
            ]
            point_geometry_count = sum(
                1
                for item in quake_events
                if isinstance(item.get("geometry"), dict)
                and item["geometry"].get("type") == "Point"
            )
            unknown_geometry_count = len(quake_events) - point_geometry_count
            payload["spatial_filter"] = {
                "mode": "earthquake_event_point_bbox",
                "context_type": "bbox",
                "event_count_after_provider_filter": len(quake_events),
                "point_geometry_count": point_geometry_count,
                "unknown_geometry_count": unknown_geometry_count,
                "complete": unknown_geometry_count == 0,
                "detection_completeness_claim": False,
            }

        if (
            candidate.public_id in _VOLCANO_PUBLIC_IDS
            and context["type"] == "bbox"
        ):
            volcano_events = [
                item for item in payload.get("events", [])
                if isinstance(item, dict)
            ]
            point_geometry_count = sum(
                1
                for item in volcano_events
                if isinstance(item.get("geometry"), dict)
                and item["geometry"].get("type") == "Point"
            )
            unknown_geometry_count = len(volcano_events) - point_geometry_count
            payload["spatial_filter"] = {
                "mode": "volcano_event_point_bbox",
                "context_type": "bbox",
                "event_count_after_provider_filter": len(volcano_events),
                "point_geometry_count": point_geometry_count,
                "unknown_geometry_count": unknown_geometry_count,
                "complete": unknown_geometry_count == 0,
                "detection_completeness_claim": False,
            }
        if candidate.public_id in _TSUNAMI_SEMANTIC_PUBLIC_IDS:
            payload = _apply_tsunami_spatial_filter(payload, context)
        payload = _filter_hazard_payload(payload, event_filter)
        return payload, result, data_time

    if mode == "data_file":
        fetch_file = getattr(candidate.provider, "async_get_data_file", None)
        if not callable(fetch_file):
            raise CandidateUnavailable(
                "temporarily_unavailable",
                retryable=True,
                message="Der Datendatei-Adapter ist nicht verfügbar.",
            )
        if trace is not None:
            trace.candidate_provider_contact(key)
        result = await fetch_file(hass, candidate.capability.id)
        if not isinstance(result, dict):
            raise ValueError("data_file provider returned no object")
        payload, data_time = _normalize_data_file(candidate, result)
        payload = apply_lightning_resource_semantics(candidate.public_id, payload)
        return payload, result, data_time

    machine_coverage: dict[str, Any] | None = None
    if mode == "raster_tile":
        machine_coverage = await _raster_machine_coverage(
            hass,
            candidate,
            context,
            trace,
        )

    if diagnostic_fault:
        mode = diagnostic_fault.get("mode")
        if trace is not None:
            trace.candidate_check(
                _candidate_trace_key(candidate),
                "diagnostic_fault",
                False,
                str(mode or "unknown"),
            )
        if mode == "resource_temporarily_unavailable":
            raise CandidateUnavailable(
                "temporarily_unavailable",
                retryable=True,
                message="Admin-Diagnose simuliert eine temporär nicht verfügbare Resource.",
            )
        if mode == "rate_limited":
            raise CandidateUnavailable(
                "rate_limited",
                retryable=True,
                message="Admin-Diagnose simuliert ein Provider-Rate-Limit.",
            )

    fetch = getattr(candidate.provider, "async_get_map_layer", None)
    if not callable(fetch):
        raise CandidateUnavailable(
            "temporarily_unavailable",
            retryable=True,
            message="Der Ressourcenadapter ist nicht verfügbar.",
        )
    if trace is not None:
        trace.candidate_provider_contact(key)
    result = await fetch(hass, candidate.capability.id)
    if not isinstance(result, dict):
        raise ValueError("resource provider returned no object")
    if diagnostic_fault and diagnostic_fault.get("mode") == "source_stale":
        if trace is not None:
            trace.candidate_check(
                _candidate_trace_key(candidate),
                "diagnostic_fault",
                False,
                "source_stale",
            )
        raise CandidateUnavailable(
            "source_stale",
            retryable=True,
            message="Admin-Diagnose simuliert nach realem Resource-Abruf eine veraltete Quelle.",
        )
    if machine_coverage is not None:
        result = dict(result)
        result["machine_coverage"] = machine_coverage

    if mode == "raster_tile":
        payload, data_time = _normalize_raster(result)
        payload = apply_lightning_resource_semantics(candidate.public_id, payload)
        payload = apply_thunder_resource_semantics(candidate.public_id, payload)
    elif mode == "image_sequence":
        payload, data_time = _normalize_image_sequence(result)
    elif mode == "live_stream":
        payload, data_time = _normalize_live_stream(result)
    elif mode == "planetary_tile":
        payload, data_time = _normalize_planetary_tile(result)
    else:
        raise CandidateUnavailable(
            "requirements_not_met",
            retryable=False,
            message=f"Resource-Typ {mode!r} ist im Consumer-Prototyp noch nicht auflösbar.",
        )

    return payload, result, data_time


def _normalize_data_file(
    candidate: Candidate,
    result: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Normalize one directly retrievable provider data file."""
    url = result.get("url")
    file_format = result.get("format")
    transport = result.get("transport", "direct")
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise CandidateUnavailable(
            "temporarily_unavailable",
            retryable=True,
            message="Die Datendatei besitzt keine gültige URL.",
        )
    if not isinstance(file_format, str) or not file_format:
        raise ValueError("data_file provider returned no format")
    if transport not in {"direct", "weather_router_proxy"}:
        raise ValueError("data_file provider returned unsupported transport")

    data_time = _iso_time(result.get("data_time"))
    valid_time = _iso_time(result.get("valid_time"))
    forecast_reference_time = _iso_time(result.get("forecast_reference_time"))
    payload = {
        "format": file_format,
        "url": url,
        "transport": transport,
        "content_type": result.get("content_type"),
        "size_bytes": result.get("size_bytes"),
        "data_time": data_time,
        "valid_time": valid_time,
        "forecast_reference_time": forecast_reference_time,
        "provenance": _source_provenance(candidate, result),
    }
    for key in ("satellite", "product", "coverage", "checksum", "metadata_url"):
        if result.get(key) is not None:
            payload[key] = result.get(key)
    return payload, data_time


def _unavailable(
    capability: str,
    code: str,
    *,
    retryable: bool,
    message: str,
) -> dict[str, Any]:
    return {
        "schema": "weather_router.consumer.resolution.v1",
        "contract_version": CONSUMER_CONTRACT_VERSION,
        "status": "unavailable",
        "capability": capability,
        "unavailable": {
            "code": code,
            "retryable": retryable,
            "message": message,
        },
    }


@websocket_api.websocket_command(
    {vol.Required("type"): "weather_router/consumer/discovery"}
)
@websocket_api.async_response
async def websocket_consumer_discovery(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return contract/version/readiness without touching provider networks."""
    ready, state = _runtime_state(hass)
    mapping_ok = True
    try:
        mapping = await _async_mapping(hass)
        hazard_catalog = await _async_hazard_types(hass)
        providers = await _async_providers(hass)
        _validate_mapping_against_providers(providers, mapping)
        _validate_hazard_mapping(mapping, hazard_catalog)
    except Exception:  # noqa: BLE001 - discovery remains available on contract failure
        mapping_ok = False
        ready = False

    connection.send_result(
        msg["id"],
        {
            "schema": "weather_router.consumer.discovery.v1",
            "contract": {
                "name": CONSUMER_CONTRACT_NAME,
                "supported_versions": [CONSUMER_CONTRACT_VERSION],
                "preferred_version": CONSUMER_CONTRACT_VERSION,
            },
            "router": {
                "ready": ready and mapping_ok,
                "enabled": bool(state["router_enabled"]),
                "integration_version": INTEGRATION_VERSION,
                "status": state["status"] if mapping_ok else "contract_mapping_invalid",
            },
            "domains": [
                {
                    "id": domain_id,
                    "enabled": domain_id in state["enabled_domains"],
                }
                for domain_id in ROUTER_DOMAINS
            ],
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/consumer/capabilities",
        vol.Required("contract_version"): int,
        vol.Optional("filter"): dict,
        vol.Optional("profile_id"): str,
    }
)
@websocket_api.async_response
async def websocket_consumer_capabilities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return provider-neutral public capability discovery without provider I/O."""
    if not _validate_contract_version(msg):
        connection.send_error(
            msg["id"],
            "unsupported_contract_version",
            str(msg.get("contract_version")),
        )
        return

    try:
        mapping = await _async_mapping(hass)
        hazard_catalog = await _async_hazard_types(hass)
        providers = await _async_providers(hass)
        _validate_mapping_against_providers(providers, mapping)
        _validate_hazard_mapping(mapping, hazard_catalog)
    except Exception as err:  # noqa: BLE001 - public contract validation is fail-closed
        connection.send_error(msg["id"], "consumer_contract_invalid", str(err))
        return

    try:
        profile_id, profile = _profile_for_request(hass, msg)
    except CandidateUnavailable as err:
        connection.send_error(msg["id"], err.code, err.message)
        return

    _ready, state = _runtime_state(hass)
    visible_public_ids = [
        public_id
        for public_id in _public_ids(mapping)
        if profile_allows_capability(profile, mapping, public_id)[0]
    ]
    # One inventory per catalog request, not once per public capability.
    # No persistent cache: changing provider/extension registries remain visible.
    capability_maps = {
        provider.id: _provider_capability_map(provider)
        for provider in providers.values()
    }
    all_rows = [
        _capability_catalog_row(
            state,
            mapping,
            hazard_catalog,
            _candidates(
                providers, mapping, public_id, capability_maps=capability_maps,
            ),
            public_id,
            profile,
        )
        for public_id in visible_public_ids
    ]
    try:
        filters = _catalog_filter(msg.get("filter"), mapping)
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_consumer_filter", str(err))
        return

    rows = [row for row in all_rows if _catalog_row_matches(row, filters)]
    connection.send_result(
        msg["id"],
        {
            "schema": "weather_router.consumer.capabilities.v1",
            "contract_version": CONSUMER_CONTRACT_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "filter_options": _catalog_filter_options(all_rows, mapping),
            "applied_filter": {
                key: sorted(value) if isinstance(value, set) else value
                for key, value in filters.items()
            },
            "profile": (
                profile_reference(profile_id, profile)
                if profile_id is not None and profile is not None
                else None
            ),
            "capabilities": rows,
        },
    )


async def _resolve_aggregate_hazard(
    hass: HomeAssistant,
    public_id: str,
    candidates: list[Candidate],
    context: dict[str, Any],
    requirements: dict[str, Any],
    event_filter: dict[str, set[str]],
    trace: RoutingTrace | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bool]:
    """Aggregate all eligible hazard sources while preserving per-event provenance."""
    if any(candidate.capability.render_mode != "hazard_feed" for candidate in candidates):
        raise ValueError("aggregate strategy is currently restricted to hazard_feed")

    events: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    failures: list[CandidateUnavailable] = []
    unfiltered_event_count = 0
    matched_source_count = 0
    source_diagnostics: list[dict[str, Any]] = []

    for candidate in candidates:
        key = _candidate_trace_key(candidate)
        if not _resource_implemented(candidate):
            failure = CandidateUnavailable(
                "requirements_not_met",
                retryable=False,
                message="Der öffentliche Ressourcenadapter ist noch nicht implementiert.",
            )
            failures.append(failure)
            if trace is not None:
                trace.candidate_result(key, result="rejected", reason=failure.code)
            continue

        started = monotonic()
        if trace is not None:
            trace.candidate_attempt(key)
        try:
            payload, provider_result, data_time = await _resolve_candidate(
                hass,
                candidate,
                context,
                requirements,
                event_filter,
                trace,
            )
            if requirements.get("timeline_required"):
                raise CandidateUnavailable(
                    "requirements_not_met",
                    retryable=False,
                    message="Ein aggregierter Gefahrenfeed besitzt keine Raster-Timeline.",
                )
            max_age = requirements.get("max_age_seconds")
            age = _age_seconds(data_time)
            if trace is not None:
                trace.candidate_freshness(
                    key,
                    {
                        "data_time": data_time,
                        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "age_seconds": age,
                        "max_age_seconds": max_age,
                        "stale": (
                            bool(age is not None and age > max_age)
                            if max_age is not None
                            else None
                        ),
                    },
                )
            if max_age is not None:
                if age is None:
                    raise CandidateUnavailable(
                        "requirements_not_met",
                        retryable=False,
                        message="Die Quelle liefert keine belastbare Datenzeit für max_age_seconds.",
                    )
                if age > max_age:
                    raise CandidateUnavailable(
                        "source_stale",
                        retryable=True,
                        message="Die Quelle überschreitet die angeforderte maximale Datenalterung.",
                    )
            source = _source_provenance(candidate, provider_result)
            sources.append(source)
            source_diagnostics.append(
                {
                    "provider_id": candidate.provider.id,
                    "capability_id": candidate.capability.id,
                    "coverage_status": payload.get("coverage_status"),
                    "geometry_status": payload.get("geometry_status"),
                    "spatial_filter": payload.get("spatial_filter"),
                    "provider_metadata": payload.get("provider_metadata"),
                    "provider_revision": payload.get("provider_revision"),
                }
            )
            unfiltered_event_count += int(
                payload.get("unfiltered_event_count", payload.get("event_count", 0)) or 0
            )
            if int(payload.get("event_count", 0) or 0) > 0:
                matched_source_count += 1
            for item in payload.get("events", []):
                if not isinstance(item, dict):
                    continue
                event = dict(item)
                source_event_id = str(event.get("id") or "")
                event["source_event_id"] = source_event_id
                event["id"] = f"{candidate.provider.id}:{source_event_id}"
                event["source_ref"] = candidate.provider.id
                events.append(event)
            if trace is not None:
                trace.candidate_result(
                    key,
                    result="selected",
                    reason="aggregate_source",
                    duration_ms=round((monotonic() - started) * 1000, 3),
                )
        except CandidateUnavailable as err:
            failures.append(err)
            if trace is not None:
                trace.candidate_result(
                    key,
                    result="rejected",
                    reason=err.code,
                    duration_ms=round((monotonic() - started) * 1000, 3),
                )
        except Exception as err:  # noqa: BLE001 - aggregate sources are isolated
            status = getattr(err, "status", None)
            failure = CandidateUnavailable(
                "rate_limited" if status == 429 else "temporarily_unavailable",
                retryable=True,
                message=(
                    "Provider ist aktuell rate-limited."
                    if status == 429
                    else "Provider konnte den Gefahrenfeed aktuell nicht liefern."
                ),
            )
            failures.append(failure)
            if trace is not None:
                trace.add_error(
                    stage="aggregate_provider",
                    code=failure.code,
                    message=str(err),
                    exception_type=type(err).__name__,
                )
                trace.candidate_result(
                    key,
                    result="failed",
                    reason=failure.code,
                    duration_ms=round((monotonic() - started) * 1000, 3),
                )

    if not sources:
        if failures and all(item.code == "outside_coverage" for item in failures):
            raise failures[-1]
        if any(item.code == "rate_limited" for item in failures):
            raise CandidateUnavailable(
                "rate_limited",
                retryable=True,
                message="Alle geeigneten Quellen sind derzeit durch Rate Limits blockiert.",
            )
        raise CandidateUnavailable(
            "temporarily_unavailable",
            retryable=True,
            message="Keine geeignete Quelle konnte den aggregierten Gefahrenfeed liefern.",
        )

    payload = {
        "events": events,
        "event_count": len(events),
        "source_count": len(sources),
        "matched_source_count": matched_source_count,
        "source_diagnostics": source_diagnostics,
    }
    if event_filter:
        payload["unfiltered_event_count"] = unfiltered_event_count
        payload["event_filter"] = _serialized_event_filter(event_filter)
        payload["filtered"] = True
    provider_result = {
        "source_class": "mixed" if len({item.get("source_class") for item in sources}) > 1 else sources[0].get("source_class"),
        "attribution": " · ".join(
            dict.fromkeys(
                str(item.get("attribution"))
                for item in sources
                if item.get("attribution")
            )
        ) or None,
    }
    provenance = _aggregate_provenance(sources)
    degraded = bool(failures)
    return payload, provider_result, provenance, degraded


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/routing_diagnostic_fault_arm",
        vol.Required("provider_id"): str,
        vol.Required("capability_id"): str,
        vol.Required("mode"): vol.In(tuple(sorted(_DIAGNOSTIC_FAULT_MODES))),
    }
)
@websocket_api.async_response
async def websocket_routing_diagnostic_fault_arm(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Arm one short-lived fault for this admin user's next Consumer resolve."""
    user_id = _diagnostic_user_id(connection)
    if user_id is None:
        connection.send_error(msg["id"], "diagnostic_user_unavailable", "Admin user id is unavailable")
        return
    store = hass.data.setdefault(_DIAGNOSTIC_FAULTS_KEY, {})
    if not isinstance(store, dict):
        store = {}
        hass.data[_DIAGNOSTIC_FAULTS_KEY] = store
    fault = {
        "provider_id": msg["provider_id"],
        "capability_id": msg["capability_id"],
        "mode": msg["mode"],
        "armed_at": monotonic(),
    }
    store[user_id] = fault
    connection.send_result(
        msg["id"],
        {
            "armed": True,
            "provider_id": fault["provider_id"],
            "capability_id": fault["capability_id"],
            "mode": fault["mode"],
            "expires_in_seconds": int(_DIAGNOSTIC_FAULT_TTL_SECONDS),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/consumer/resolve",
        vol.Required("contract_version"): int,
        vol.Required("capability"): str,
        vol.Required("context"): dict,
        vol.Required("time"): dict,
        vol.Optional("requirements"): dict,
        vol.Optional("event_filter"): dict,
        vol.Optional("profile_id"): str,
        vol.Optional("consumer_id"): str,
        vol.Optional("correlation_id"): str,
    }
)
@websocket_api.async_response
async def websocket_consumer_resolve(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Resolve one public capability and record an admin-only decision trace."""
    from .consumer_api_monitor import monitored_connection
    connection = monitored_connection(hass, connection, msg, "V1")
    public_id = str(msg.get("capability") or "")
    trace = begin_routing_trace(
        hass,
        capability=public_id,
        contract_version=msg.get("contract_version"),
    )
    # Correlate this precise trace without relying on global latest-trace order.
    if getattr(connection, "_ticket", None) is not None:
        connection._monitor_trace = trace
    diagnostic_fault = _consume_diagnostic_fault(hass, connection)
    profile_meta: dict[str, Any] | None = None

    def _finish_unavailable(
        code: str,
        *,
        retryable: bool,
        message: str,
        stage: str,
    ) -> None:
        result = _unavailable(
            public_id,
            code,
            retryable=retryable,
            message=message,
        )
        if profile_meta is not None:
            result["profile"] = profile_meta
        trace.add_error(stage=stage, code=code, message=message)
        trace.set_decision(status="unavailable", code=code)
        trace.finish(status="unavailable", code=code)
        connection.send_result(msg["id"], result)

    def _finish_error(code: str, message: str, stage: str) -> None:
        trace.add_error(stage=stage, code=code, message=message)
        trace.set_decision(status="error", code=code)
        trace.finish(status="error", code=code)
        connection.send_error(msg["id"], code, message)

    if not _validate_contract_version(msg):
        _finish_error(
            "unsupported_contract_version",
            str(msg.get("contract_version")),
            "contract",
        )
        return

    if not _PUBLIC_ID_RE.fullmatch(public_id):
        _finish_error("invalid_capability", public_id, "request")
        return

    try:
        context = _context(msg)
        time_context = _time_context(msg)
        requirements = _requirements(msg)
    except CandidateUnavailable as err:
        _finish_unavailable(
            err.code,
            retryable=err.retryable,
            message=err.message,
            stage="request",
        )
        return
    except (TypeError, ValueError, vol.Invalid) as err:
        _finish_error("invalid_consumer_request", str(err), "request")
        return

    trace.set_context(context_diagnostics(context))
    trace.set_request(
        context_type=context["type"],
        time_mode=time_context["mode"],
        requirements=requirements,
        profile_id=msg.get("profile_id"),
    )

    ready, state = _runtime_state(hass)
    trace.set_policy(
        {
            "router_ready": ready,
            "router_enabled": state["router_enabled"],
            "enabled_domains": sorted(state["enabled_domains"]),
            "enabled_provider_count": len(state["enabled_providers"]),
            "routing_uses": context_diagnostics(context).get("routing_uses"),
            "implicit_reference_location_used": False,
        }
    )
    if not ready:
        _finish_unavailable(
            "router_not_ready",
            retryable=True,
            message="WeatherRouter ist noch nicht betriebsbereit.",
            stage="router",
        )
        return
    if not state["router_enabled"]:
        _finish_unavailable(
            "router_disabled",
            retryable=False,
            message="WeatherRouter wurde vom Benutzer deaktiviert.",
            stage="router",
        )
        return

    domain = public_id.split(".", 1)[0]
    if domain not in ROUTER_DOMAINS:
        _finish_unavailable(
            "capability_not_supported",
            retryable=False,
            message="Die angefragte öffentliche Capability ist nicht bekannt.",
            stage="domain",
        )
        return
    if domain not in state["enabled_domains"]:
        _finish_unavailable(
            "domain_disabled",
            retryable=False,
            message="Der zugehörige WeatherRouter-Fachbereich ist deaktiviert.",
            stage="domain",
        )
        return

    trace.stage_start("contract_and_catalog")
    try:
        mapping = await _async_mapping(hass)
        hazard_catalog = await _async_hazard_types(hass)
        providers = await _async_providers(hass)
        _validate_mapping_against_providers(providers, mapping)
        _validate_hazard_mapping(mapping, hazard_catalog)
    except Exception as err:  # noqa: BLE001
        trace.stage_end("contract_and_catalog")
        trace.add_error(
            stage="contract_and_catalog",
            code="consumer_contract_invalid",
            message=str(err),
            exception_type=type(err).__name__,
        )
        _finish_error("consumer_contract_invalid", str(err), "contract_and_catalog")
        return
    trace.stage_end("contract_and_catalog")

    trace.set_request(
        family=_public_family(mapping, public_id),
        phenomena=_public_phenomena(mapping, public_id),
    )
    trace_policy = dict(trace.data.get("policy", {}))
    intent_contract = _public_intent_contract(mapping, public_id)
    if intent_contract is not None:
        trace_policy["intent_contract"] = intent_contract
    trace.set_policy(trace_policy)

    try:
        profile_id, profile = _profile_for_request(hass, msg)
    except CandidateUnavailable as err:
        _finish_unavailable(
            err.code,
            retryable=err.retryable,
            message=err.message,
            stage="profile",
        )
        return

    profile_meta = (
        profile_reference(profile_id, profile)
        if profile_id is not None and profile is not None
        else None
    )
    trace.set_profile(profile_meta)
    if profile_meta is not None:
        trace.set_request(
            profile_id=profile_id,
            profile_revision=int(profile_meta.get("revision") or 0),
        )

    allowed_by_profile, profile_reason = profile_allows_capability(
        profile,
        mapping,
        public_id,
    )
    if not allowed_by_profile:
        _finish_unavailable(
            "profile_filtered",
            retryable=False,
            message="Die angefragte Capability ist durch das Consumer-Profil ausgeschlossen.",
            stage="profile",
        )
        return

    try:
        event_filter = _event_filter(msg, hazard_catalog)
        _validate_event_filter_for_capability(mapping, public_id, event_filter)
        if _public_hazard_types(mapping, public_id):
            event_filter, profile_filter_conflict = apply_profile_event_filter(
                profile,
                event_filter,
            )
            if profile_filter_conflict:
                raise CandidateUnavailable(
                    "profile_filtered",
                    retryable=False,
                    message="Der angeforderte Ereignisfilter liegt außerhalb des Consumer-Profils.",
                )
            _validate_event_filter_for_capability(mapping, public_id, event_filter)
    except CandidateUnavailable as err:
        _finish_unavailable(
            err.code,
            retryable=err.retryable,
            message=err.message,
            stage="event_filter",
        )
        return
    except (TypeError, ValueError, vol.Invalid) as err:
        _finish_error("invalid_consumer_request", str(err), "event_filter")
        return

    trace.set_request(event_filter=_serialized_event_filter(event_filter))

    trace.stage_start("eligibility")
    all_candidates = _candidates(providers, mapping, public_id)
    trace.set_providers_checked(len(all_candidates))
    trace.set_request(
        resource_types=sorted(
            {candidate.capability.render_mode for candidate in all_candidates}
        )
    )
    if not all_candidates:
        trace.stage_end("eligibility")
        _finish_unavailable(
            "capability_not_supported",
            retryable=False,
            message="Die angefragte öffentliche Capability ist nicht registriert.",
            stage="eligibility",
        )
        return

    if time_context["mode"] == "events_intersecting_window":
        from .consumer_event_time_policy import validate_event_time
        try:
            if "max_age_seconds" in requirements:
                raise ValueError("event windows use separate feed age, not max_age_seconds")
            time_context = validate_event_time(
                time_context, public_id=public_id,
                resource_types={item.capability.render_mode for item in all_candidates},
            )
        except (ValueError, TypeError) as err:
            trace.stage_end("eligibility")
            _finish_error("invalid_consumer_request", str(err), "event_time")
            return
        trace.set_request(event_time_policy=time_context)
    for order, candidate in enumerate(all_candidates):
        key = _candidate_trace_key(candidate)
        raw_extension_id = getattr(candidate.provider, "weather_router_extension_id", None)
        extension_id = (
            str(raw_extension_id)
            if isinstance(raw_extension_id, str) and raw_extension_id
            else None
        )
        candidate_scope = "extension" if extension_id else "standard_core"
        trace.add_candidate(
            key=key,
            provider_id=candidate.provider.id,
            provider_name=candidate.provider.name,
            candidate_scope=candidate_scope,
            extension_id=extension_id,
            capability_id=candidate.capability.id,
            resource_type=candidate.capability.render_mode,
            source_class=candidate.capability.source_class,
            order=order,
            network_targets=_provider_network_targets(candidate.provider),
            intent=public_id,
            topics=_candidate_topics(mapping, candidate),
            data_origin=str(candidate.semantics.get("data_origin") or "unspecified"),
            measurement_method=str(
                candidate.semantics.get("measurement_method") or "unspecified"
            ),
            observation_kind=str(
                candidate.semantics.get("observation_kind") or "unspecified"
            ),
            quantity=str(candidate.semantics.get("quantity") or "unspecified"),
            unit=(
                str(candidate.semantics.get("unit"))
                if candidate.semantics.get("unit") is not None
                else None
            ),
            time_semantics=(
                dict(candidate.semantics.get("time_semantics"))
                if isinstance(candidate.semantics.get("time_semantics"), dict)
                else None
            ),
            coverage_semantics=(
                dict(candidate.semantics.get("coverage_semantics"))
                if isinstance(candidate.semantics.get("coverage_semantics"), dict)
                else None
            ),
            routing_score=list(candidate.score),
        )

        provider_domains = set(getattr(candidate.provider, "router_domains", ("weather",)))
        router_ok = bool(state["router_enabled"])
        domain_ok = domain in state["enabled_domains"] and domain in provider_domains
        provider_ok = candidate.provider.id in state["enabled_providers"]
        provider_profile_ok = profile_allows_provider(profile, candidate.provider.id)
        candidate_profile_ok, candidate_profile_reason = profile_allows_candidate(
            profile,
            candidate.semantics,
        )
        profile_ok = provider_profile_ok and candidate_profile_ok
        profile_reason = (
            "profile_provider_filtered"
            if not provider_profile_ok
            else candidate_profile_reason
        )
        resource_ok = _resource_implemented(candidate)
        context_ok = _context_supported(candidate, context)
        resource_type_ok = (
            "resource_types" not in requirements
            or candidate.capability.render_mode in requirements["resource_types"]
        )
        source_class_ok = (
            "source_classes" not in requirements
            or candidate.capability.source_class in requirements["source_classes"]
        )
        coverage_contract_ok, coverage_contract_reason = _coverage_contract_allows(
            mapping,
            candidate,
        )
        trace.candidate_check(key, "router_enabled", router_ok, None if router_ok else "router_disabled")
        trace.candidate_check(key, "domain_enabled", domain_ok, None if domain_ok else "domain_disabled")
        trace.candidate_check(key, "provider_enabled", provider_ok, None if provider_ok else "provider_disabled")
        trace.candidate_check(
            key,
            "profile_allowed",
            profile_ok,
            None if profile_ok else profile_reason or "profile_filtered",
        )
        trace.candidate_check(
            key,
            "candidate_policy",
            candidate_profile_ok,
            None if candidate_profile_ok else candidate_profile_reason,
        )
        trace.candidate_check(
            key,
            "coverage_declared",
            coverage_contract_ok,
            None if coverage_contract_ok else coverage_contract_reason,
        )
        trace.candidate_check(key, "resource_implemented", resource_ok, None if resource_ok else "requirements_not_met")
        trace.candidate_check(key, "context_supported", context_ok, None if context_ok else "requirements_not_met")
        trace.candidate_check(key, "resource_type", resource_type_ok, None if resource_type_ok else "requirements_not_met")
        trace.candidate_check(key, "source_class", source_class_ok, None if source_class_ok else "requirements_not_met")

    if (
        public_id in _POINT_GEOMETRY_REQUIRED_PUBLIC_IDS
        and context["type"] == "point"
    ):
        trace.stage_end("eligibility")
        for candidate in all_candidates:
            trace.candidate_result(
                _candidate_trace_key(candidate),
                result="rejected",
                reason="requirements_not_met",
            )
        _finish_unavailable(
            "requirements_not_met",
            retryable=False,
            message=(
                (
                    "Civil-Point-Abfragen benötigen eine explizite "
                    if public_id in _CIVIL_PROTECTION_PUBLIC_IDS
                    else "Sicherheits-Point-Abfragen benötigen eine explizite "
                )
                + "Point-in-Geometry- oder Distanzsemantik. "
                + "Bitte BBOX oder Global verwenden."
            ),
            stage="eligibility",
        )
        return

    globally_enabled_candidates = [
        candidate
        for candidate in all_candidates
        if _candidate_enabled(state, candidate.provider, public_id)[0]
    ]
    profile_candidates = [
        candidate
        for candidate in globally_enabled_candidates
        if profile_allows_provider(profile, candidate.provider.id)
        and profile_allows_candidate(profile, candidate.semantics)[0]
    ]
    profile_excluded_candidates = (
        len(globally_enabled_candidates) - len(profile_candidates)
    )
    eligible = [
        candidate
        for candidate in profile_candidates
        if _context_supported(candidate, context)
        and _requirements_match(candidate, requirements)
        and _coverage_contract_allows(mapping, candidate)[0]
    ]
    trace.stage_end("eligibility")

    eligible_keys = {_candidate_trace_key(candidate) for candidate in eligible}
    for candidate in all_candidates:
        key = _candidate_trace_key(candidate)
        if key in eligible_keys:
            continue
        checks = next(
            (item.get("checks", {}) for item in trace.data["candidates"] if item.get("key") == key),
            {},
        )
        reason = next(
            (
                info.get("reason")
                for info in checks.values()
                if isinstance(info, dict) and info.get("passed") is False and info.get("reason")
            ),
            "not_eligible",
        )
        trace.candidate_result(key, result="rejected", reason=reason)

    if not eligible:
        if globally_enabled_candidates and not profile_candidates and profile is not None:
            code = "profile_filtered"
            message = (
                "Alle global geeigneten Provider wurden durch das Consumer-Profil "
                "ausgeschlossen."
            )
        else:
            code = "requirements_not_met" if profile_candidates else "no_eligible_provider"
            message = (
                "Kein aktivierter Provider erfüllt Kontext und harte Anforderungen."
                if profile_candidates
                else "Für diese Capability ist kein aktivierter Provider verfügbar."
            )
        _finish_unavailable(
            code,
            retryable=False,
            message=message,
            stage="eligibility",
        )
        return

    strategy = _resolution_strategy(mapping, public_id)
    if strategy == "aggregate":
        trace.stage_start("provider_resolution")
        try:
            payload, provider_result, provenance, degraded = await _resolve_aggregate_hazard(
                hass,
                public_id,
                eligible,
                context,
                requirements,
                event_filter,
                trace,
            )
        except CandidateUnavailable as err:
            trace.stage_end("provider_resolution")
            _finish_unavailable(
                err.code,
                retryable=err.retryable,
                message=err.message,
                stage="provider_resolution",
            )
            return
        except Exception as err:
            trace.stage_end("provider_resolution")
            trace.add_error(
                stage="provider_resolution",
                code="consumer_contract_invalid",
                message=str(err),
                exception_type=type(err).__name__,
            )
            _finish_error(
                "consumer_contract_invalid",
                "Aggregate capability is not compatible with its mapped resource types.",
                "provider_resolution",
            )
            return
        trace.stage_end("provider_resolution")

        if time_context["mode"] == "events_intersecting_window":
            from .consumer_event_time_policy import filter_event_payload
            payload = filter_event_payload(
                payload, time=time_context, provider_result=provider_result)
            trace.set_request(event_time_result=payload["event_time_policy"])
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        freshness = {
            "data_time": None,
            "fetched_at": now,
            "age_seconds": None,
            "stale": None,
        }
        result = {
            "schema": "weather_router.consumer.resolution.v1",
            "contract_version": CONSUMER_CONTRACT_VERSION,
            "status": "ready",
            "capability": public_id,
            "resource": {
                "type": "hazard_feed",
                "payload": payload,
            },
            "provenance": provenance,
            "freshness": freshness,
            "profile": profile_meta,
            "routing": {
                "reason_code": "aggregate_eligible_sources",
                "fallback_available": False,
                "degraded": degraded,
                "candidate_count": len(eligible),
                "selected_count": len(provenance["sources"]),
                "profile_excluded_candidates": profile_excluded_candidates,
            },
        }
        trace.set_resource("hazard_feed", payload, provider_result)
        trace.set_freshness(freshness)
        trace.set_decision(
            status="ready",
            selected_provider="aggregate",
            selected_capability=public_id,
            fallback_count=trace.recorded_fallback_count(),
            reason_code="aggregate_eligible_sources",
        )
        trace.finish(status="ready")
        connection.send_result(msg["id"], result)
        return

    failures: list[CandidateUnavailable] = []
    rate_limited = False
    trace.stage_start("provider_resolution")

    for index, candidate in enumerate(eligible):
        key = _candidate_trace_key(candidate)
        if not _resource_implemented(candidate):
            failure = CandidateUnavailable(
                "requirements_not_met",
                retryable=False,
                message="Der öffentliche Ressourcenadapter ist noch nicht implementiert.",
            )
            failures.append(failure)
            trace.candidate_result(key, result="rejected", reason=failure.code)
            continue

        candidate_started = monotonic()
        trace.candidate_attempt(key)
        try:
            payload, provider_result, data_time = await _resolve_candidate(
                hass,
                candidate,
                context,
                requirements,
                event_filter,
                trace,
                diagnostic_fault=(
                    diagnostic_fault
                    if _fault_matches_candidate(diagnostic_fault, candidate)
                    else None
                ),
            )

            _validate_intent_resource_contract(
                mapping,
                public_id,
                candidate,
                payload,
            )

            if time_context["mode"] == "events_intersecting_window":
                from .consumer_event_time_policy import filter_event_payload
                payload = filter_event_payload(
                    payload, time=time_context, provider_result=provider_result)
                trace.set_request(event_time_result=payload["event_time_policy"])

            age = _age_seconds(data_time)
            max_age = requirements.get("max_age_seconds")
            trace.candidate_freshness(
                key,
                {
                    "data_time": data_time,
                    "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "age_seconds": age,
                    "max_age_seconds": max_age,
                    "stale": (
                        bool(age is not None and age > max_age)
                        if max_age is not None
                        else None
                    ),
                },
            )
            if max_age is not None:
                if age is None:
                    raise CandidateUnavailable(
                        "requirements_not_met",
                        retryable=False,
                        message="Die Quelle liefert keine belastbare Datenzeit für max_age_seconds.",
                    )
                if age > max_age:
                    raise CandidateUnavailable(
                        "source_stale",
                        retryable=True,
                        message="Die Quelle überschreitet die angeforderte maximale Datenalterung.",
                    )

            if requirements.get("timeline_required") and not isinstance(payload.get("timeline"), dict):
                raise CandidateUnavailable(
                    "requirements_not_met",
                    retryable=False,
                    message="Die angefragte Quelle besitzt keine Timeline.",
                )

            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            reason = trace.winner_reason(
                eligible_count=len(eligible),
                rate_limited=rate_limited,
            )
            freshness = {
                "data_time": data_time,
                "fetched_at": now,
                "age_seconds": age,
                "stale": (
                    bool(max_age is not None and age is not None and age > max_age)
                    if max_age is not None
                    else None
                ),
            }
            result = {
                "schema": "weather_router.consumer.resolution.v1",
                "contract_version": CONSUMER_CONTRACT_VERSION,
                "status": "ready",
                "capability": public_id,
                "resource": {
                    "type": candidate.capability.render_mode,
                    "semantics": dict(candidate.semantics),
                    "payload": payload,
                },
                "provenance": _provenance(candidate, provider_result),
                "freshness": freshness,
                "profile": profile_meta,
                "intent_contract": _public_intent_contract(mapping, public_id),
                "routing": {
                    "reason_code": reason,
                    "fallback_available": len(eligible) > 1,
                    "degraded": trace.recorded_fallback_count() > 0,
                    "candidate_count": len(eligible),
                    "selected_index": index,
                    "profile_excluded_candidates": profile_excluded_candidates,
                },
            }
            trace.candidate_result(
                key,
                result="selected",
                reason=reason,
                duration_ms=round((monotonic() - candidate_started) * 1000, 3),
            )
            trace.set_resource(candidate.capability.render_mode, payload, provider_result)
            trace.set_freshness(freshness)
            trace.set_decision(
                status="ready",
                selected_provider=candidate.provider.id,
                selected_capability=candidate.capability.id,
                selected_index=index,
                fallback_count=trace.recorded_fallback_count(),
                reason_code=reason,
            )
            trace.stage_end("provider_resolution")
            trace.finish(status="ready")
            connection.send_result(msg["id"], result)
            return
        except CandidateUnavailable as err:
            failures.append(err)
            trace.candidate_result(
                key,
                result="rejected",
                reason=err.code,
                duration_ms=round((monotonic() - candidate_started) * 1000, 3),
            )
            if err.code == "rate_limited":
                rate_limited = True
        except Exception as err:  # noqa: BLE001 - provider isolation/fallback is intentional
            status = getattr(err, "status", None)
            code = "rate_limited" if status == 429 else "temporarily_unavailable"
            if status == 429:
                rate_limited = True
            failure = CandidateUnavailable(
                code,
                retryable=True,
                message=(
                    "Provider ist aktuell rate-limited."
                    if status == 429
                    else "Provider konnte die angefragte Capability aktuell nicht liefern."
                ),
            )
            failures.append(failure)
            trace.add_error(
                stage="provider_resolution",
                code=code,
                message=str(err),
                exception_type=type(err).__name__,
            )
            trace.candidate_result(
                key,
                result="failed",
                reason=code,
                duration_ms=round((monotonic() - candidate_started) * 1000, 3),
            )

    trace.stage_end("provider_resolution")
    if failures:
        if all(item.code == "outside_coverage" for item in failures):
            final = failures[-1]
        elif any(item.code == "rate_limited" for item in failures):
            final = CandidateUnavailable(
                "rate_limited",
                retryable=True,
                message="Alle geeigneten Quellen sind derzeit durch Rate Limits blockiert.",
            )
        elif any(item.code == "temporarily_unavailable" for item in failures):
            final = CandidateUnavailable(
                "temporarily_unavailable",
                retryable=True,
                message="Alle geeigneten Quellen sind derzeit vorübergehend nicht verfügbar.",
            )
        else:
            final = failures[-1]
    else:
        final = CandidateUnavailable(
            "no_eligible_provider",
            retryable=False,
            message="Es wurde kein geeigneter Provider gefunden.",
        )

    _finish_unavailable(
        final.code,
        retryable=final.retryable,
        message=final.message,
        stage="provider_resolution",
    )


def async_register(hass: HomeAssistant) -> None:
    """Register only Consumer API V1 commands.

    Consumer API V2 is registered once by __init__.py through
    consumer_raster_mosaic_api.async_register().
    """
    websocket_api.async_register_command(hass, websocket_consumer_discovery)
    websocket_api.async_register_command(hass, websocket_consumer_capabilities)
    websocket_api.async_register_command(hass, websocket_routing_diagnostic_fault_arm)
    websocket_api.async_register_command(hass, websocket_consumer_resolve)
