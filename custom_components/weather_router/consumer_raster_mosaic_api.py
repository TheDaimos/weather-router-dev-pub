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
from .spatial_coverage import CoverageTemporarilyUnavailable, normalize_coverage

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
        vol.Optional("source_request"): dict,
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

    # Explicit OPERA requests are a fail-closed source selection, never automatic
    # fallback to DWD/NASA. Until independently approved scientific raster
    # delivery exists, return a stable denial with no raster URL.
    if isinstance(query.get("source_request"), dict) and query["source_request"].get("provider_id") == "opera":
        from .const import DOMAIN, CONF_ENABLED_PROVIDERS, CONF_ROUTER_ENABLED
        entries = hass.config_entries.async_entries(DOMAIN)
        entry = entries[0] if entries else None
        options = entry.options if entry is not None else {}
        enabled = (
            bool(options.get(CONF_ROUTER_ENABLED, True))
            and "opera" in options.get(CONF_ENABLED_PROVIDERS, ())
        )
        # OPERA-PROVIDER-02: reject disabled/unsupported products before any
        # ring rehydration, S3 refresh or tile access. Neither provider opt-in
        # nor service opt-in is scientific approval.
        from .opera_config import service_allowed
        product = query["source_request"].get("product_id")
        if not service_allowed(options, product) or product != "RATE":
            connection.send_result(msg["id"], {
                "contract_version": 2,
                "capability": query["capability"],
                "source_request": dict(query["source_request"]),
                "provider_id": "opera", "product_id": product,
                "source_id": None,
                "correlation_id": query.get("correlation_id"),
                "status": "disabled" if not service_allowed(options, product) else "active_blocked",
                "block_reason": "opera_service_disabled" if not service_allowed(options, product)
                                else "opera_product_not_scientifically_approved",
                "raster_approved": False, "scientific_status": "UNVERIFIED",
                "valid_at": None, "age_seconds": None,
                "layers": [], "tile_urls": [], "fallback_performed": False,
            })
            return
        from .opera_v2_admission import explicit_rate_response, registered_rate_response, diagnostic_rate_response
        # Server-owned installation only. Requests cannot supply registrations,
        # scientific booleans, user identity or provider permissions.
        from .opera_rate_registry import RateTileRegistry
        state = hass.data.get(DOMAIN, {})
        staged = state.get("opera_rate_delivery") if isinstance(state, dict) else None
        response = None
        # Explicit developer-only orientation selector; never a scientific V2 layer.
        preview_hypothesis = query["source_request"].get("preview_orientation")
        preview_requested = preview_hypothesis in ("north_first", "south_first")
        # VIS-07: use the same persisted administrator consent as the
        # OPERA HTTP preview view and preview_control websocket command.
        # hass.data["opera_preview"] is not an authorization source.
        from .opera_preview_age_policy import preview_continuity_from_entries
        continuity = preview_continuity_from_entries(hass.config_entries.async_entries(DOMAIN))
        preview_max_age = continuity["delivery_limit_seconds"]
        preview_enabled = any(
            candidate.options.get("opera_dev_preview_enabled") is True
            for candidate in hass.config_entries.async_entries(DOMAIN)
        )
        # Diagnostic-only gate snapshot. Server computed; never a permission grant.
        diagnostic_requested = query["source_request"].get("diagnostic") is True
        user = getattr(connection, "user", None)
        route_active = isinstance(staged, dict) and staged.get("http_route_active") is True
        registry = staged.get("registry") if isinstance(staged, dict) else None
        authorize = staged.get("profile_authorizer") if isinstance(staged, dict) else None
        registry_ready = isinstance(registry, RateTileRegistry)
        authorizer_ready = callable(authorize)
        profile_allowed = False
        if route_active and registry_ready and authorizer_ready and user is not None:
            try:
                profile_allowed = authorize(user, query) is True
            except Exception:  # diagnostic may never change deny-by-default
                profile_allowed = False
        stamp = getattr(staged.get("delivery"), "current_stamp", None) if isinstance(staged, dict) else None
        registration_ready = False
        diagnostic_registered = False
        if registry_ready and isinstance(stamp, str):
            try:
                registration_ready = registry.lookup("RATE", stamp) is not None
                diagnostic_registered = registry.is_diagnostic("RATE", stamp) is True
            except Exception:
                registration_ready = False
                diagnostic_registered = False
        # Rehydrate a vetted, recent original from the persisted OPERA ring.
        # This is a DEV-admin diagnostic path only. Do not grant scientific approval.
        async def restore_ring_preview():
            ring_state = state.get("opera_ring_buffer", {}) if isinstance(state, dict) else {}
            store = ring_state.get("store") if isinstance(ring_state, dict) else None
            delivery = staged.get("delivery") if isinstance(staged, dict) else None
            if store is None or delivery is None or not preview_enabled:
                return False
            from datetime import datetime, timezone
            from hashlib import sha256
            from .opera_odim_metadata import inspect_odim_hdf5
            from .opera_odim_reconstruction import reconstruct_laea

            def _restore():
                catalog = store.verified_frame_catalog()
                now = datetime.now(timezone.utc)
                candidates = sorted(catalog, key=lambda f: f["stamp"], reverse=True)
                for candidate in candidates:
                    stamp_text = candidate["stamp"]
                    stamp_time = datetime.strptime(stamp_text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                    age = (now - stamp_time).total_seconds()
                    if not 0 <= age <= preview_max_age:
                        continue
                    if isinstance(delivery.current_stamp, str) and delivery.current_stamp >= stamp_text:
                        return False
                    try:
                        with store.read_frame(stamp_text) as original:
                            metadata = inspect_odim_hdf5(original, expected_product="RATE")
                            verified = datetime.fromisoformat(metadata.valid_at.replace("Z", "+00:00"))
                            if (verified != stamp_time or metadata.product != "RATE"
                                    or metadata.geographic_corners is None or metadata.pixel_scale is None
                                    or metadata.raster_approved is True):
                                continue
                            digest = sha256()
                            with original.open("rb") as handle:
                                for chunk in iter(lambda: handle.read(65536), b""):
                                    digest.update(chunk)
                            if digest.hexdigest() != candidate["sha256"]:
                                continue
                            grid = reconstruct_laea(
                                projection=metadata.projection,
                                corners=metadata.geographic_corners,
                                width=metadata.width, height=metadata.height,
                                xscale=metadata.pixel_scale[0], yscale=metadata.pixel_scale[1],
                                row_zero_north=True,
                            )
                            delivery.stage_local_rate(
                                trusted_path=original, expected_sha256=digest.hexdigest(),
                                diagnostic_grid=grid,
                                attribution="EUMETNET OPERA · Unverified DEV",
                            )
                            return True
                    except (OSError, ValueError, KeyError, TypeError):
                        continue
                return False

            return await hass.async_add_executor_job(_restore)

        # Explicit admin-only diagnostic refresh; production mosaics never fetch OPERA.
        refresh_status = "not_requested"
        if (diagnostic_requested and (not preview_requested or preview_enabled)
                and enabled and route_active and registry_ready
                and profile_allowed and getattr(user, "is_admin", False) is True):
            from datetime import datetime, timezone
            fresh = False
            if registration_ready and diagnostic_registered:
                try:
                    t = registry.lookup("RATE", stamp).frame.valid_at
                    age = (datetime.now(timezone.utc) - t.astimezone(timezone.utc)).total_seconds()
                    fresh = 0 <= age <= preview_max_age
                except (AttributeError, TypeError, ValueError):
                    pass
            if fresh:
                refresh_status = "existing_fresh_frame"
            else:
                restored = False
                try:
                    async with asyncio.timeout(15):
                        restored = await restore_ring_preview()
                except (asyncio.TimeoutError, ValueError, OSError):
                    restored = False
                if restored:
                    refresh_status = "ring_frame_rehydrated_unverified"
                else:
                    from .providers.opera import OperaProvider
                    try:
                        async with asyncio.timeout(45):
                            refresh = await OperaProvider().async_diagnostics(hass, "opera_rate_discovery")
                        refresh_status = ("registered_unverified"
                                          if refresh.get("diagnostic_frame_registered") is True
                                          else "no_fresh_frame_or_stage_failed")
                    except (asyncio.TimeoutError, ValueError, OSError):
                        refresh_status = "refresh_failed"
                stamp = getattr(staged.get("delivery"), "current_stamp", None)
                registration_ready = isinstance(stamp, str) and registry.lookup("RATE", stamp) is not None
                diagnostic_registered = isinstance(stamp, str) and registry.is_diagnostic("RATE", stamp) is True
        if isinstance(staged, dict) and staged.get("http_route_active") is True:
            registry = staged.get("registry")
            authorize = staged.get("profile_authorizer")
            if isinstance(registry, RateTileRegistry) and callable(authorize):
                # Current HA-authenticated connection identity and server-side
                # profile policy must both approve the exact request.
                try:
                    user = getattr(connection, "user", None)
                    approved = (authorize(user, query) is True) if user is not None else False
                except Exception:  # fail closed; no profile exception or identity leak
                    approved = False
                if approved is True:
                    stamp = getattr(staged.get("delivery"), "current_stamp", None)
                    if query["source_request"].get("diagnostic") is True:
                        response = diagnostic_rate_response(
                            enabled=enabled,
                            correlation_id=query.get("correlation_id"),
                            capability=query["capability"],
                            source_request={"provider_id": "opera", "product_id": "RATE",
                                            "diagnostic": True},
                            registry=registry, stamp=stamp,
                            admin_authorized=(getattr(user, "is_admin", False) is True),
                            max_age_seconds=preview_max_age)
                    else:
                        response = registered_rate_response(
                            enabled=enabled,
                            correlation_id=query.get("correlation_id"),
                            capability=query["capability"],
                            source_request=query["source_request"],
                            registry=registry, stamp=registry.current_approved_stamp(),
                            profile_authorized=True, max_age_seconds=preview_max_age)
        if preview_requested and not preview_enabled:
            response = None
        result = response if response is not None else explicit_rate_response(
            enabled=enabled,
            correlation_id=query.get("correlation_id"),
            capability=query["capability"],
            source_request=({"provider_id": "opera", "product_id": "RATE", "diagnostic": True}
                            if preview_requested else query["source_request"]),
        )
        if preview_requested:
            # Explicit, non-operational overlay only. Unverified pixels must never
            # enter the approved tile route or automatic provider selection.
            if (preview_enabled and isinstance(response, dict)
                    and response.get("status") == "diagnostic_unverified"
                    and response.get("tile_urls")
                    and getattr(user, "is_admin", False) is True):
                preview_url = (
                    f"/api/weather_router/opera_preview/RATE/{stamp}/"
                    f"{preview_hypothesis}/{{z}}/{{x}}/{{y}}.png"
                )
                result["status"] = "UNVERIFIED_DEV_PREVIEW"
                result["block_reason"] = "scientific_orientation_unverified"
                result["preview_only"] = True
                result["preview_orientation"] = preview_hypothesis
                result["scientific_status"] = "UNVERIFIED / ENTWICKLUNGSVORSCHAU"
                result["raster_approved"] = False
                result["max_age_seconds"] = continuity["freshness_seconds"]
                result["stale_after_seconds"] = continuity["stale_after_seconds"]
                from datetime import datetime, timezone
                observation_time = registry.lookup("RATE", stamp).frame.valid_at
                observation_age = max(0, (datetime.now(timezone.utc) -
                    observation_time.astimezone(timezone.utc)).total_seconds())
                is_stale = observation_age > continuity["stale_after_seconds"]
                result["historical_preview_available"] = continuity["serve_stale"] and is_stale
                result["preview_age_status"] = "stale" if is_stale else "current"
                result["age_seconds"] = round(observation_age, 2)
                result["observation_time"] = observation_time.astimezone(timezone.utc).isoformat()
                result["delivery_limit_seconds"] = preview_max_age
                result["freshness_policy"] = "USER_CONFIGURED_OPERA_PREVIEW"
                result["observation_age_seconds"] = result.get("age_seconds")
                result["cache_policy"] = "no-store"
                result["tile_urls"] = [preview_url]
                result["layers"] = [{
                    "provider_id": "opera", "product_id": "RATE",
                    "unit": "mm/h", "render_mode": "raster_tile",
                    "tile_url": preview_url,
                    "orientation_hypothesis": preview_hypothesis,
                    "scientific_status": "UNVERIFIED / ENTWICKLUNGSVORSCHAU",
                    "quality_status": "UNVERIFIED",
                    "tile_format": "image/png",
                    "nodata_handling": "transparent_alpha_zero",
                    "georeference_status": "ORIGINAL_METADATA_HYPOTHESIS",
                    "projection": registry.lookup("RATE", stamp).projection,
                    "projected_bounds": list(registry.lookup("RATE", stamp).grid.bounds),
                    "projected_pixel_size": list(registry.lookup("RATE", stamp).grid.pixel_size),
                    "attribution": registry.lookup("RATE", stamp).attribution,
                }]
            else:
                result["status"] = "active_blocked"
                # Preserve deny-by-default, but report which gate prevents the
                # explicit developer preview. Never treat this as authorization.
                from datetime import datetime, timezone
                frame_fresh = False
                if registration_ready and registry_ready and isinstance(stamp, str):
                    try:
                        frame = registry.lookup("RATE", stamp).frame
                        age = (datetime.now(timezone.utc) -
                               frame.valid_at.astimezone(timezone.utc)).total_seconds()
                        frame_fresh = 0 <= age <= preview_max_age
                    except (AttributeError, TypeError, ValueError, OverflowError):
                        pass
                if getattr(user, "is_admin", False) is not True:
                    preview_block_reason = "administrator_required"
                elif not preview_enabled:
                    preview_block_reason = "preview_consent_disabled"
                elif enabled is not True:
                    preview_block_reason = "opera_provider_disabled"
                elif not route_active:
                    preview_block_reason = "opera_http_route_inactive"
                elif not registry_ready:
                    preview_block_reason = "opera_tile_registry_unavailable"
                elif not authorizer_ready:
                    preview_block_reason = "opera_profile_authorizer_unavailable"
                elif not profile_allowed:
                    preview_block_reason = "opera_profile_not_authorized"
                elif not isinstance(stamp, str):
                    preview_block_reason = "opera_current_frame_missing"
                elif not registration_ready:
                    preview_block_reason = "opera_rate_frame_not_registered"
                elif not diagnostic_registered:
                    preview_block_reason = "opera_frame_not_diagnostic"
                elif not frame_fresh:
                    preview_block_reason = "opera_rate_frame_stale"
                elif not isinstance(response, dict):
                    preview_block_reason = "opera_preview_response_unavailable"
                elif response.get("status") != "diagnostic_unverified":
                    preview_block_reason = "opera_preview_response_blocked"
                elif not response.get("tile_urls"):
                    preview_block_reason = "opera_preview_tile_urls_missing"
                else:
                    preview_block_reason = "opera_preview_contract_blocked"
                result["block_reason"] = preview_block_reason
                result["raster_approved"] = False
                result["tile_urls"] = []
                result["layers"] = []
                result["preview_only"] = True

        if diagnostic_requested:
            # A registered stamp can remain present after its freshness window.
            # Report validity separately from existence, never extend the window.
            from datetime import datetime, timezone
            frame_age_seconds = None
            frame_fresh = False
            if registration_ready and registry_ready and isinstance(stamp, str):
                try:
                    frame = registry.lookup("RATE", stamp).frame
                    frame_age_seconds = round((datetime.now(timezone.utc) -
                        frame.valid_at.astimezone(timezone.utc)).total_seconds(), 2)
                    frame_fresh = 0 <= frame_age_seconds <= preview_max_age
                except (AttributeError, TypeError, ValueError, OverflowError):
                    frame_fresh = False
            registered_utc = None
            if registration_ready and registry_ready and isinstance(stamp, str):
                try:
                    registered_utc = registry.lookup("RATE", stamp).frame.valid_at.astimezone(
                        timezone.utc).isoformat().replace("+00:00", "Z")
                except (AttributeError, TypeError, ValueError):
                    pass
            age_reason = ("frame_not_registered" if frame_age_seconds is None else
                          "frame_in_future" if frame_age_seconds < 0 else
                          "frame_expired" if frame_age_seconds > preview_max_age else
                          "within_configured_limit")
            test68_diagnostic = {
                "test_id": "TEST68-G",
                "frame": {"registered_stamp": stamp, "observation_utc": registered_utc,
                          "age_seconds": frame_age_seconds},
                "preview_policy": {
                    "configured_max_age_seconds": continuity["freshness_seconds"],
                    "effective_max_age_seconds": preview_max_age,
                    "stale_after_seconds": continuity["stale_after_seconds"],
                    "serve_stale": continuity["serve_stale"]},
                "orientation": {name: {"eligible": frame_fresh, "reason": age_reason}
                                for name in ("north_first", "south_first")},
                "blocking_gate": age_reason if not frame_fresh else None,
                "scientific_approval": False}
            gates = {
                "preview_consent_enabled": preview_enabled is True,
                "provider_enabled": enabled is True,
                "http_route_active": route_active,
                "registry_available": registry_ready,
                "profile_authorizer_available": authorizer_ready,
                "authenticated_user_present": user is not None,
                "admin_authorized": getattr(user, "is_admin", False) is True,
                "profile_authorized": profile_allowed,
                "current_stamp_available": isinstance(stamp, str),
                "registered_rate_frame": registration_ready,
                "diagnostic_registration": diagnostic_registered,
                "registered_frame_fresh": frame_fresh,
            }
            failed = [key for key, passes in gates.items() if not passes]
            # Only authenticated administrators can receive gate booleans.
            diagnostic = {
                "schema": "weather_router.opera_diagnostic_gates.v1",
                "passed": len(failed) == 0,
                "failed_gates": failed,
                "gates": gates,
                "scientific_release": False,
                "frame_age_seconds": frame_age_seconds,
                "max_frame_age_seconds": preview_max_age,
                "stale_after_seconds": continuity["stale_after_seconds"],
                "serve_stale": continuity["serve_stale"],
                "refresh_status": refresh_status,
                "test68_g": test68_diagnostic,
            }
            if getattr(user, "is_admin", False) is True:
                result["diagnostic_gates"] = diagnostic
            else:
                result["diagnostic_gates"] = {
                    "schema": "weather_router.opera_diagnostic_gates.v1",
                    "passed": False, "failed_gates": ["administrator_required"],
                    "scientific_release": False,
                }
        from .diagnostic_center import record as d2_record
        d2_record(hass, category="consumer",
                  outcome="success" if result.get("diagnostic_only") is True else "unavailable",
                  correlation_id=query.get("correlation_id"),
                  details={"selected_count": len(result.get("tile_urls") or ())})
        connection.send_result(msg["id"], result)
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

            from .opera_preview_age_policy import preview_continuity_from_entries
            from .const import DOMAIN
            configured_entries = hass.config_entries.async_entries(DOMAIN)
            query["time"]["max_data_age_seconds"] = preview_continuity_from_entries(
                configured_entries)["freshness_seconds"]
            from .nasa_mosaic import OPTION, NASA, NasaMetadataPreparation, configured_parallel
            nasa_configured = bool(configured_entries and configured_entries[0].options.get(OPTION,False) is True)
            nasa_enabled = nasa_configured and "tile_zoom" in query["context"]
            nasa_runtime = hass.data.setdefault(DOMAIN,{})
            if not nasa_configured:
                previous_job=nasa_runtime.pop("nasa_metadata_preparation",None)
                if previous_job:previous_job.close()
            coverage_memory=nasa_runtime.setdefault("nasa_reservation_envelopes",{}) if nasa_enabled else {}
            nasa_unknown=[]
            wants_background = query["time"].pop("allow_older_satellite_background", False) is True
            query["time"].pop("max_background_age_seconds", None)
            if wants_background:
                query["time"]["max_background_age_seconds"] = 43200

            context = {key: value for key, value in query["context"].items()
                       if key not in ("focus", "tile_zoom", "raster_contract")}
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
                    if nasa_enabled and source_id==NASA:
                        job=nasa_runtime.setdefault("nasa_metadata_preparation",NasaMetadataPreparation(on_ready=lambda:hass.bus.async_fire("weather_router_routing_changed",{"nasa_metadata_ready":True})))
                        async def prepare_nasa():
                            # One separately bounded metadata job cannot occupy radar slots.
                            raw_coverage=await getter(hass,row.capability.id)
                            checked=normalize_coverage(raw_coverage)
                            if checked is None:raise ValueError("unverified_nasa_coverage")
                            raw=await row.provider.async_get_map_layer(hass,row.capability.id)
                            payload,data_time=_normalize_raster(raw)
                            return {"coverage":checked,"payload":{**payload,"frame_time":data_time}}
                        cached=job.peek_or_start(prepare_nasa)
                        if cached is None:
                            status="metadata_unavailable" if job.error else "metadata_pending"
                            return None
                        status="coverage_accepted"
                        async def read_prepared():return cached["payload"]
                        return {"source_id":source_id,"eligible":True,"machine_coverage":cached["coverage"],
                                "semantics":dict(row.semantics),"routing_score":tuple(row.score),
                                "retrieved_at":job.retrieved_at,"async_fetch":read_prepared}
                    # DWD has a verified-only, nonblocking coverage interface.
                    # It coalesces cold WMS requests and publishes a readiness
                    # event later. Other providers retain their bounded legacy
                    # preflight; do not transfer WR scientific admission to GR.
                    ready_getter = getattr(
                        row.provider, "async_get_coverage_ready", None
                    )
                    if row.provider.id == "dwd" and callable(ready_getter):
                        slot_acquired_at = clock.time()
                        coverage_raw = await ready_getter(hass, row.capability.id)
                        provider_finished_at = clock.time()
                        if coverage_raw is None:
                            status = "coverage_pending"
                            return None
                    else:
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
                    if nasa_enabled and not source_id.startswith("nasa_gibs/"):
                        if len(coverage_memory)<12 or source_id in coverage_memory:coverage_memory[source_id]=coverage
                    if viewport_overlap(viewport, coverage) <= 0 and not nasa_enabled:
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
                except CoverageTemporarilyUnavailable:
                    status = "temporarily_unavailable"
                    return None
                except Exception:  # noqa: BLE001 - avoid leaking provider internals
                    return None
                finally:
                    if nasa_enabled and not source_id.startswith("nasa_gibs/") and status not in ("coverage_accepted","outside_coverage"):
                        # The previous snapshot is not a proof after the
                        # DWD layer-specific cache has actually expired.
                        # Other providers retain conservative envelopes until
                        # their own validity can be verified.
                        if row.provider.id == "dwd":
                            inspector = getattr(row.provider, "coverage_preflight_diagnostics", None)
                            if callable(inspector):
                                try:
                                    proof = inspector(row.capability.id)
                                    if isinstance(proof, dict) and proof.get("cache_valid") is False:
                                        coverage_memory.pop(source_id, None)
                                except Exception:
                                    pass
                        if source_id not in coverage_memory:
                            nasa_unknown.append(source_id)
                    ended = clock.time()
                    entry = {
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
                    }
                    # Optional provider-neutral, local state snapshot: on a
                    # timed-out request the coverage result itself is absent.
                    # Never include raw exceptions, URLs, XML or coordinates.
                    detail = getattr(
                        row.provider, "coverage_preflight_diagnostics", None
                    )
                    if callable(detail):
                        try:
                            state = detail(row.capability.id)
                            if isinstance(state, dict):
                                allowed = {
                                    "cache_valid", "cache_ttl_remaining_seconds",
                                    "refresh_running", "lookup_stage",
                                    "aggregate_wms_cached",
                                    "global_wms_refresh_running",
                                    "retry_after_seconds",
                                    "refresh_scheduled_in_seconds",
                                    "last_verified_at_utc",
                                    "refresh_reason",
                                    "wms_request_stage",
                                    "network_wait_ms",
                                    "xml_parse_ms",
                                    "bbox_validation_ms",
                                    "wms_failure_kind",
                                }
                                entry["provider_state"] = {
                                    k: v for k, v in state.items() if k in allowed
                                    and isinstance(v, (bool, int, float, str, type(None)))
                                }
                        except Exception:  # noqa: BLE001 - diagnostics cannot break routing
                            pass
                    coverage_preflight.append(entry)

            if _LIVE_REQUEST_SLOTS.locked():
                connection.send_error(
                    msg["id"], "mosaic_busy",
                    "Eine begrenzte Zahl von Mosaikanfragen wird bereits verarbeitet."
                )
                return
            async with _LIVE_REQUEST_SLOTS:
                scanned = await asyncio.gather(*(_source(row) for row in preflight))
                sources = [row for row in scanned if row is not None]
                if nasa_enabled:
                    present_ids={row["source_id"] for row in sources}
                    authorized_ids={f"{row.provider.id}/{row.capability.id}" for row in unique.values()}
                    for source_id in authorized_ids:
                        if not source_id.startswith("nasa_gibs/") and source_id not in present_ids and source_id not in coverage_memory:
                            nasa_unknown.append(source_id)
                    for source_id,coverage in coverage_memory.items():
                        if source_id in authorized_ids and source_id not in present_ids:
                            sources.append({"source_id":source_id,"eligible":False,"machine_coverage":coverage})
                opera_decision = {"source_id": "opera/opera_rate_raster",
                                  "result": "provider_or_profile_disabled"}
                # Only WR may insert a trusted OPERA candidate into normal V2.
                # Diagnostic frames and browser-supplied approval never qualify.
                # OPERA is an optional independent primary provider. Failure of
                # its registry, stamp, policy or candidate reconstruction MUST
                # NOT abort a verified DWD or NASA mosaic. A runtime failure is
                # indeterminate (not proof of no OPERA geography): NASA still
                # fails closed when the active radar extent is unverified.
                try:
                    if ("opera" in state["enabled_providers"]
                            and profile_allows_provider(profile, "opera")):
                        from .const import DOMAIN
                        from .opera_config import service_allowed, read_config
                        from .opera_runtime_candidate import registered_rate_mosaic_source
                        entries = hass.config_entries.async_entries(DOMAIN)
                        options = entries[0].options if entries else {}
                        runtime = hass.data.get(DOMAIN, {})
                        staged = runtime.get("opera_rate_delivery") if isinstance(runtime, dict) else None
                        opera_decision["result"] = "rate_disabled_or_route_inactive"
                        if (service_allowed(options, "RATE") and isinstance(staged, dict)
                                and staged.get("http_route_active") is True):
                            registry = staged.get("registry")
                            delivery = staged.get("delivery")
                            authorize = staged.get("profile_authorizer")
                            user = getattr(connection, "user", None)
                            try:
                                permitted = (user is not None and callable(authorize)
                                             and authorize(user, query) is True)
                            except Exception:
                                permitted = False
                            opera_decision["result"] = "consumer_not_authorized"
                            if permitted and delivery is not None:
                                opera_decision["result"] = "no_admitted_current_frame"
                                candidate = registered_rate_mosaic_source(
                                    registry, registry.current_approved_stamp(),
                                    max_age_seconds=preview_continuity_from_entries(entries)["delivery_limit_seconds"],
                                    stale_after_seconds=read_config(options)["stale_after_seconds"])
                                if (candidate is not None
                                        and profile_allows_candidate(
                                            profile, candidate["semantics"])[0]):
                                    sources.append(candidate)
                                    if nasa_enabled:coverage_memory["opera/opera_rate_raster"]=candidate["machine_coverage"]
                                    opera_decision["result"] = "admitted_for_planning"
                                elif candidate is not None:
                                    opera_decision["result"] = "profile_semantics_filtered"
                                else:
                                    stamp = registry.current_approved_stamp()
                                    registered = registry.lookup("RATE", stamp) if stamp else None
                                    if registered and (datetime.now(timezone.utc)-registered.frame.valid_at).total_seconds() > preview_continuity_from_entries(entries)["delivery_limit_seconds"]:
                                        opera_decision["result"] = "frame_expired"
                                        coverage_memory.pop("opera/opera_rate_raster", None)
                except Exception:  # provider-local failure, no unsafe exception details
                    sources[:] = [row for row in sources if
                                  row.get("source_id") != "opera/opera_rate_raster"]
                    opera_decision["result"] = "opera_runtime_unavailable"
                    # Keep previously verified geometry for conservative NASA
                    # reservation if available; never infer absence from error.
                from .nasa_primary_policy import reconcile_opera_reservation
                opera_fallback_reason = reconcile_opera_reservation(
                    opera_decision, coverage_memory, nasa_unknown, sources,
                    nasa_enabled=nasa_enabled,
                    opera_allowed=("opera" in state["enabled_providers"]
                                   and profile_allows_provider(profile, "opera")),
                )
                try:
                    config_path = getattr(getattr(hass, "config", None), "path", None)
                    dwd_cache = config_path("weather_router", "dwd-validity") if callable(config_path) else None
                    result = await resolve_mosaic_snapshot(query, sources=sources, nasa_complement=nasa_enabled,nasa_coverage_uncertain=bool(nasa_unknown),nasa_parallelism=configured_parallel(configured_entries[0].options) if configured_entries else 6,nasa_transport_revision=configured_entries[0].options.get("nasa_transport_revision",0) if configured_entries else 0,dwd_validity_cache=dwd_cache)
                    if result.get("spatial_contract_version") == 2 and dwd_cache is not None:
                        # Entirely detached from the consumer/provider deadline.
                        # The first resolve remains conservative; the next one
                        # can use a verified, exact-frame WCS validity mask.
                        from .dwd_mask_scheduler import maybe_schedule_dwd_mask
                        result.setdefault("spatial_planning", {})["dwd_mask_preparation"] = (
                            maybe_schedule_dwd_mask(hass, result, dwd_cache))
                    if nasa_enabled:
                        job=nasa_runtime.get("nasa_metadata_preparation")
                        if job:
                            progress=result.setdefault("nasa_mosaic",{})
                            progress.update(job.diagnostic())
                            if result.get("spatial_contract_version")==2:
                                progress["pending_replan"]=bool(progress.get("metadata_pending") and not progress.get("plan_complete"))
                        progress = result.setdefault("nasa_mosaic", {})
                        # Fixed, bounded source IDs and states only. These
                        # distinguish no-frame fallback from a DWD timeout
                        # without leaking capability URLs or coordinates.
                        progress["opera_fallback_reason"] = opera_fallback_reason
                        progress["primary_coverage_blockers"] = sorted(
                            set(nasa_unknown)
                        )[:MAX_COVERAGE_CONTACTS]
                        progress["primary_coverage_uncertain"] = bool(nasa_unknown)
                        # This is the accepted NASA raster candidate state,
                        # not merely a preflight coverage descriptor.
                        progress["provider_admitted"] = (
                            progress.get("provider_admitted") is True
                        )
                        progress["tiles_authorized"] = bool(
                            progress.get("authorized_tile_count", 0)
                        )
                        progress["actually_rendered"] = None  # GR owns rendering
                        nasa_runtime["nasa_mosaic_status"]={k:v for k,v in progress.items() if k not in ("tiles","projected_viewport")}
                except Exception:  # noqa: BLE001 - fail closed without provider details
                    connection.send_error(msg["id"], "mosaic_temporarily_unavailable",
                                          "Die mehrteilige Rasterauflösung ist derzeit nicht verfügbar.")
                    return
                rejected_sources = result.pop("_internal_source_rejections", [])
                # Additive V2 source outcomes are the consumer's authoritative
                # source-specific decision, not solely monitor-only details.
                # Coverage is checked first, then fetch/time/composition.
                # Only catalogue source IDs and fixed, bounded reason codes.
                selected_ids = {
                    row["source_id"] for row in result.get("layers", [])
                    if isinstance(row, dict)
                    and isinstance(row.get("source_id"), str)
                }
                rejection_codes = {
                    str(item.get("source_id"))[:128]: str(item.get("reason"))[:72]
                    for item in rejected_sources[:MAX_COVERAGE_CONTACTS]
                    if isinstance(item, dict)
                    and isinstance(item.get("source_id"), str)
                    and isinstance(item.get("reason"), str)
                }
                outcome_rows = []
                for item in sorted(coverage_preflight,
                                   key=lambda row: row["source_id"]):
                    source_id = item["source_id"]
                    state = item["result"]
                    if source_id in selected_ids:
                        state = "selected"
                    elif state == "coverage_accepted":
                        state = rejection_codes.get(source_id, "not_selected")
                    outcome_rows.append({
                        "source_id": source_id,
                        "result": state,
                    })
                if opera_decision["result"] == "admitted_for_planning":
                    opera_decision["result"] = ("selected" if opera_decision["source_id"] in selected_ids
                                                else rejection_codes.get(opera_decision["source_id"], "not_selected"))
                outcome_rows = [opera_decision, *[row for row in outcome_rows
                                if row["source_id"] != opera_decision["source_id"]]]
                hass.data.setdefault(DOMAIN, {})["opera_rate_routing"] = dict(opera_decision)
                result["source_outcomes"] = outcome_rows[:MAX_COVERAGE_CONTACTS]
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
                        "delivered_sources": [
                            item["source_id"] for item in result.get("layers", [])
                        ][:MAX_COVERAGE_CONTACTS],
                        "layer_order": result.get("layer_order"),
                        "source_outcomes": result["source_outcomes"],
                        "dwd_validity": result.get("spatial_planning", {}).get("dwd_validity"),
                        "dwd_mask_lookup_ms": result.get("spatial_planning", {}).get("dwd_mask_lookup_ms"),
                        "dwd_mask_cache_hit": result.get("spatial_planning", {}).get("dwd_mask_cache_hit"),
                        "dwd_mask_preparation": result.get("spatial_planning", {}).get("dwd_mask_preparation"),
                        "spatial_plan_ms": result.get("spatial_planning", {}).get("plan_ms"),
                        "coverage_preflight": sorted(coverage_preflight,
                            key=lambda item: item["source_id"])[:MAX_COVERAGE_CONTACTS],
                        "final_layers_count": len(result.get("layers", [])),
                        "source_rejections": rejected_sources,
                        "limits": query["limits"],
                        "limitations": result.get("limitations", []),
                    }
                from .diagnostic_center import record as d2_record
                d2_record(hass, category="consumer", outcome="success",
                          correlation_id=query.get("correlation_id"),
                          details={"selected_count": len(result.get("layers") or ())})
                connection.send_result(msg["id"], result)

    except TimeoutError:
        connection.send_error(
            msg["id"], "mosaic_timeout",
            "Die zeitlich begrenzte Mosaikauflösung wurde abgebrochen."
        )


def async_register(hass: HomeAssistant) -> None:
    """Register additive opt-in Consumer V2, preserving all V1 routes."""
    websocket_api.async_register_command(hass, websocket_consumer_resolve_mosaic)
