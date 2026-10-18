"""P7-010 experimental opt-in, read-only Consumer V2 raster mosaic API.

This endpoint is independent of V1 resolve, does not alter legacy responses,
does not select providers by name or country, and never accepts client
eligibility flags. It is staged ONLY in the public DEV branch until full HA
integration tests and deployment approval have been completed.
"""
from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .consumer_profiles import (
    profile_allows_capability,
    profile_allows_candidate,
    profile_allows_provider,
)
from .raster_mosaic_contract import (
    MosaicContractError,
    validate_raster_mosaic_request,
)
from .raster_mosaic_policy import viewport_overlap
from .raster_mosaic_service import resolve_mosaic_snapshot
from .spatial_coverage import normalize_coverage

MAX_COVERAGE_CONTACTS = 12
MAX_COVERAGE_CONCURRENT = 3
# DWD-WMS-Metadaten koennen beim kalten Erstaufruf mehr als 3 s benoetigen.
# Das getrennte globale V2-Limit bleibt bei 16 s; V1 unveraendert.
COVERAGE_TIMEOUT_SECONDS = 6.0
# End-to-end provider processing deadline. V1 remains unaffected.
MOSAIC_PROVIDER_DEADLINE_SECONDS = 16.0
# Coverage preflights share a limit across clients, not only per request.
_GLOBAL_COVERAGE_LOOP = None
_GLOBAL_COVERAGE_SLOTS = None


def _shared_coverage_slots():
    """Share coverage contact slots among consumers on one HA event loop."""
    global _GLOBAL_COVERAGE_LOOP, _GLOBAL_COVERAGE_SLOTS
    loop = asyncio.get_running_loop()
    if loop is not _GLOBAL_COVERAGE_LOOP:
        _GLOBAL_COVERAGE_LOOP = loop
        _GLOBAL_COVERAGE_SLOTS = asyncio.Semaphore(MAX_COVERAGE_CONCURRENT)
    return _GLOBAL_COVERAGE_SLOTS
def _catalog_failure_code(error: Exception) -> str:
    """Use only stable, source-neutral error classes; never expose paths or secrets."""
    if isinstance(error, FileNotFoundError):
        missing = getattr(error, "filename", None)
        if isinstance(missing, str) and missing.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] == "provider_time_contracts.v1.json":
            return "consumer_time_registry_missing"
    if isinstance(error, ValueError) and str(error) in {
        "provider_time_contract_provider_inventory_drift",
        "provider_time_contract_capability_inventory_drift",
        "invalid_provider_time_contract_schema",
        "invalid_provider_time_contract_providers",
        "invalid_provider_time_contract_provider",
        "invalid_provider_time_contract_capability",
        "invalid_provider_time_contract_status",
        "invalid_provider_time_contract_fields",
        "invalid_provider_time_field",
        "invalid_provider_time_format",
        "invalid_provider_time_role",
        "provider_time_evidence_missing",
        "invalid_provider_epoch_time_basis",
    }:
        return "consumer_time_registry_invalid"
    return "consumer_contract_invalid"


# Two simultaneous full V2 requests at most, even during rapid map movements.
_LIVE_REQUEST_SLOTS = asyncio.Semaphore(2)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/consumer/resolve_mosaic",
        vol.Required("contract_version"): int,
        vol.Required("capability"): str,
        vol.Required("context"): dict,
        vol.Required("time"): dict,
        vol.Required("limits"): dict,
        vol.Optional("profile_id"): str,
        vol.Optional("consumer_id"): str,
        vol.Optional("correlation_id"): str,
    }
)
@websocket_api.async_response
async def websocket_consumer_resolve_mosaic(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Resolve multiple eligible precipitation rasters, never mutate V1."""
    from .consumer_api_monitor import monitored_connection
    connection = monitored_connection(hass, connection, msg, "V2")
    try:
        query = validate_raster_mosaic_request(
            {key: value for key, value in msg.items() if key != "id"}
        )
    except (MosaicContractError, TypeError, ValueError) as exc:
        connection.send_error(msg["id"], "invalid_mosaic_request", str(exc))
        return

    # This deadline covers catalogue/profile discovery as well as all provider
    # coverage and raster phases, including global semaphore waiting.
    try:
        async with asyncio.timeout(MOSAIC_PROVIDER_DEADLINE_SECONDS):
            # Importing core helpers only on entry avoids circular dependency during
            # V1 module registration. All authorization decisions stay in WR Core.
            from .consumer_api import (
                CandidateUnavailable,
                _async_mapping,
                _async_providers,
                _candidate_enabled,
                _candidates,
                _context_supported,
                _coverage_contract_allows,
                _normalize_raster,
                _profile_for_request,
                _resource_implemented,
                _runtime_state,
                _validate_mapping_against_providers,
            )

            ready, state = _runtime_state(hass)
            if not ready or not state["router_enabled"]:
                connection.send_error(msg["id"], "router_not_ready",
                                      "WeatherRouter ist nicht betriebsbereit.")
                return
            if "weather" not in state["enabled_domains"]:
                connection.send_error(msg["id"], "domain_disabled",
                                      "Wetterdaten sind im Router deaktiviert.")
                return
            try:
                mapping = await _async_mapping(hass)
                providers = await _async_providers(hass)
                _validate_mapping_against_providers(providers, mapping)
                profile_id, profile = _profile_for_request(hass, msg)
                profile_ok, _ = profile_allows_capability(
                    profile, mapping, query["capability"])
            except CandidateUnavailable as exc:
                connection.send_error(msg["id"], exc.code, exc.message)
                return
            except Exception as exc:  # noqa: BLE001 - never leak secrets or provider internals
                connection.send_error(msg["id"], _catalog_failure_code(exc),
                                      "Providerkatalog oder Consumer-Vertrag ist nicht verfügbar.")
                return
            if not profile_ok:
                connection.send_error(msg["id"], "profile_filtered",
                                      "Das Consumer-Profil schließt diese Capability aus.")
                return

            context = {key: value for key, value in query["context"].items()
                       if key != "focus"}
            viewport = {key: context[key] for key in ("west", "east", "south", "north")}
            candidates = _candidates(providers, mapping, query["capability"])
            authorized = [
                row for row in candidates
                if row.capability.render_mode == "raster_tile"
                and _candidate_enabled(state, row.provider, row.public_id)[0]
                and profile_allows_provider(profile, row.provider.id)
                and profile_allows_candidate(profile, row.semantics)[0]
                and _context_supported(row, context)
                and _coverage_contract_allows(mapping, row)[0]
                and _resource_implemented(row)
                and callable(getattr(row.provider, "async_get_coverage", None))
            ]

            # Explicit bounded metadata preflight, before any raster provider contact.
            # Machine coverage is never guessed from a provider's name or country.
            # Preserve Core's provider-neutral candidate score, rather than allowing
            # incidental catalog order to determine which candidates get preflight.
            # Python's stable sort retains catalog order only for equal scores.
            ranked = sorted(authorized, key=lambda row: tuple(row.score))
            # Duplicate catalog entries must not spend several coverage calls on the
            # same provider capability. Keep the best-ranked authorized descriptor.
            unique = {}
            for row in ranked:
                key = (row.provider.id, row.capability.id)
                unique.setdefault(key, row)
            # Select in score-preserving rounds across distinct providers. A provider
            # exposing many capabilities cannot consume every discovery slot before
            # another authorized provider receives its first chance. No additional
            # contact is made, and no unverified geographic extent is inferred.
            remaining = list(unique.values())
            preflight = []
            while remaining and len(preflight) < MAX_COVERAGE_CONTACTS:
                seen_providers = set()
                next_round = []
                for row in remaining:
                    if (row.provider.id not in seen_providers
                            and len(preflight) < MAX_COVERAGE_CONTACTS):
                        preflight.append(row)
                        seen_providers.add(row.provider.id)
                    else:
                        next_round.append(row)
                remaining = next_round

            coverage_slots = _shared_coverage_slots()
            coverage_preflight: list[dict[str, Any]] = []

            async def _source(row: Any) -> dict[str, Any] | None:
                getter = getattr(row.provider, "async_get_coverage", None)
                # Public catalogue IDs only; never leak URLs, provider
                # exceptions, location coordinates or GetCapabilities XML.
                source_id = f"{row.provider.id}/{row.capability.id}"
                status = "coverage_provider_error"
                cache_hit = False
                clock = asyncio.get_running_loop()
                started = clock.time()
                slot_acquired_at: float | None = None
                provider_finished_at: float | None = None
                try:
                    async with coverage_slots:
                        slot_acquired_at = clock.time()
                        coverage_raw = await asyncio.wait_for(
                            getter(hass, row.capability.id),
                            timeout=COVERAGE_TIMEOUT_SECONDS,
                        )
                        provider_finished_at = clock.time()
                    coverage = normalize_coverage(coverage_raw)
                    if coverage is None:
                        status = "coverage_invalid"
                        return None
                    cache = coverage.get("cache")
                    cache_hit = bool(cache.get("hit") is True) if isinstance(cache, dict) else False
                    if viewport_overlap(viewport, coverage) <= 0:
                        status = "outside_coverage"
                        return None

                    async def _fetch() -> dict[str, Any]:
                        raw = await row.provider.async_get_map_layer(
                            hass, row.capability.id)
                        if not isinstance(raw, dict):
                            raise ValueError("invalid raster result")
                        sanitized, data_time = _normalize_raster(raw)
                        return {**sanitized, "frame_time": data_time}

                    status = "coverage_accepted"
                    return {
                        "source_id": source_id,
                        "eligible": True,
                        "machine_coverage": coverage,
                        "semantics": dict(row.semantics),
                        "routing_score": tuple(row.score),
                        "async_fetch": _fetch,
                    }
                except TimeoutError:
                    status = "coverage_timeout"
                    return None
                except Exception:  # noqa: BLE001 - avoid leaking provider internals
                    return None
                finally:
                    ended = clock.time()
                    coverage_preflight.append({
                        "source_id": source_id[:128],
                        "result": status,
                        "duration_ms": round((ended - started) * 1000, 2),
                        "slot_wait_ms": round(
                            (slot_acquired_at - started) * 1000, 2)
                        if slot_acquired_at is not None else None,
                        "provider_wait_ms": round(
                            ((provider_finished_at or ended) - slot_acquired_at) * 1000, 2)
                        if slot_acquired_at is not None else None,
                        "cache_hit": cache_hit,
                    })

            if _LIVE_REQUEST_SLOTS.locked():
                connection.send_error(
                    msg["id"], "mosaic_busy",
                    "Eine begrenzte Zahl von Mosaikanfragen wird bereits verarbeitet."
                )
                return
            async with _LIVE_REQUEST_SLOTS:
                scanned = await asyncio.gather(*(_source(row) for row in preflight))
                sources = [row for row in scanned if row is not None]
                try:
                    result = await resolve_mosaic_snapshot(query, sources=sources)
                except Exception:  # noqa: BLE001 - fail closed without provider details
                    connection.send_error(msg["id"], "mosaic_temporarily_unavailable",
                                          "Die mehrteilige Rasterauflösung ist derzeit nicht verfügbar.")
                    return
                rejected_sources = result.pop("_internal_source_rejections", [])
                if len(unique) > len(preflight):
                    result["limitations"].append(
                        "Weitere berechtigte Quellen wurden durch das Coverage-Kontaktbudget nicht geprüft.")
                if len(sources) < len(preflight):
                    result["limitations"].append(
                        "Einige regionale Coverage-Anfragen waren nicht nutzbar.")
                if getattr(connection, "_ticket", None) is not None:
                    connection._monitor_routing = {
                        "contact_budget": MAX_COVERAGE_CONTACTS,
                        "coverage_concurrent": MAX_COVERAGE_CONCURRENT,
                        "contacts_selected": len(preflight),
                        "sources_eligible": len(sources),
                        "selected_sources": [item["source_id"] for item in sources[:MAX_COVERAGE_CONTACTS]],
                        "coverage_preflight": sorted(coverage_preflight,
                            key=lambda item: item["source_id"])[:MAX_COVERAGE_CONTACTS],
                        "final_layers_count": len(result.get("layers", [])),
                        "source_rejections": rejected_sources,
                        "limits": query["limits"],
                        "limitations": result.get("limitations", []),
                    }
                connection.send_result(msg["id"], result)

    except TimeoutError:
        connection.send_error(
            msg["id"], "mosaic_timeout",
            "Die zeitlich begrenzte Mosaikauflösung wurde abgebrochen."
        )


def async_register(hass: HomeAssistant) -> None:
    """Register additive opt-in Consumer V2, preserving all V1 routes."""
    websocket_api.async_register_command(hass, websocket_consumer_resolve_mosaic)
