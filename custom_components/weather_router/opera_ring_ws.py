"""Administrator-only OPERA ring controls; no historical tile permissions."""
from __future__ import annotations

from functools import partial
import voluptuous as vol
from homeassistant.components import websocket_api

from .const import DOMAIN, CONF_ENABLED_PROVIDERS, CONF_ROUTER_ENABLED, DEV_BUILD_VERSION, DEV_LOADER_REV


def _state(hass):
    return hass.data.get(DOMAIN, {}).get("opera_ring_buffer", {})


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "weather_router/opera/ring",
    vol.Optional("action", default="status"): vol.In(
        ("status", "set_monitor", "check_now", "cleanup", "clear", "historical_select", "historical_list", "verified_catalog", "historical_compare", "historical_reset")),
    vol.Optional("enabled"): bool,
    vol.Optional("interval"): vol.In((15, 20, 30, 60)),
    vol.Optional("confirm"): bool,
    vol.Optional("stamp"): str,
    vol.Optional("z"): vol.All(vol.Coerce(int), vol.Range(min=0, max=12)),
    vol.Optional("x"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("y"): vol.All(vol.Coerce(int), vol.Range(min=0)),
})
@websocket_api.async_response
async def ws_opera_ring(hass, connection, msg):
    state = _state(hass)
    store = state.get("store")
    if store is None:
        connection.send_error(msg["id"], "ring_unavailable", "OPERA ring unavailable")
        return
    monitor = state.get("monitor")
    action = msg["action"]
    if action != "status":
        entries = hass.config_entries.async_entries(DOMAIN)
        if (len(entries) != 1
                or entries[0].options.get(CONF_ROUTER_ENABLED, True) is not True
                or "opera" not in entries[0].options.get(CONF_ENABLED_PROVIDERS, ())):
            connection.send_error(msg["id"], "provider_disabled", "OPERA is disabled")
            return
    try:
        if action == "set_monitor":
            if monitor is None or "enabled" not in msg:
                raise ValueError("invalid_monitor_options")
            interval = msg.get("interval", monitor.interval)
            enabled = msg["enabled"]
            from .opera_config import service_allowed
            entries = hass.config_entries.async_entries(DOMAIN)
            if not enabled and any(service_allowed(entry.options, "RATE") for entry in entries):
                raise ValueError("rate_monitor_owned_by_provider")
            await monitor.stop()
            monitor.interval, monitor.enabled = interval, enabled
            state["monitor_enabled"], state["poll_interval_seconds"] = enabled, interval
            entries = hass.config_entries.async_entries(DOMAIN)
            options = dict(entries[0].options)
            options.update(opera_ring_monitor_enabled=enabled,
                           opera_ring_poll_seconds=interval)
            hass.config_entries.async_update_entry(entries[0], options=options)
            await monitor.start()
        elif action == "check_now":
            if monitor is None or not monitor.enabled:
                raise ValueError("monitor_not_enabled")
            await monitor.check_once()
        elif action == "historical_list":
            frames = await hass.async_add_executor_job(store.list_frames)
            connection.send_result(msg["id"], {
                "schema": "weather_router.opera.historical_v2.diagnostic.v1",
                "frames": frames[-96:], "scientific_status": "UNVERIFIED",
                "historical_tile_authorized": False, "tile_url": None,
            })
            return
        elif action == "verified_catalog":
            # Administrator-only, hash-verified metadata. Deliberately no pixel
            # data, tile URLs, approval flags or cross-boundary live promotion.
            catalog = await hass.async_add_executor_job(store.verified_frame_catalog)
            connection.send_result(msg["id"], {
                "schema": "weather_router.opera.verified_catalog.v1",
                "frames": catalog[-96:],
                "scientific_status": "UNVERIFIED",
                "historical_tile_authorized": False,
                "raster_approved": False,
            })
            return
        elif action == "historical_reset":
            state.pop("test68_selection", None)
            connection.send_result(msg["id"], {
                "schema": "weather_router.opera.test68.reset.v1",
                "historical_mode": False, "scientific_approval": False})
            return
        elif action == "historical_compare":
            selection = state.get("test68_selection")
            if not isinstance(selection, dict) or msg.get("stamp") != selection.get("stamp"):
                raise ValueError("historical_selection_required")
            from .opera_historical_compare import compare_pinned_original
            output = await hass.async_add_executor_job(partial(
                compare_pinned_original, original=selection["original"],
                expected_sha256=selection["sha256"], stamp=selection["stamp"],
                z=msg.get("z", 6), x=msg.get("x", 33), y=msg.get("y", 20)))
            if output["selected_frame_sha256"] != selection["sha256"]:
                raise ValueError("historical_frame_changed")
            from .opera_preview_age_policy import preview_continuity_from_entries
            policy = preview_continuity_from_entries(hass.config_entries.async_entries(DOMAIN))
            output["configured_preview_validity_seconds"] = policy["freshness_seconds"]
            output["effective_preview_validity_seconds"] = policy["delivery_limit_seconds"]
            output["stale_after_seconds"] = policy["stale_after_seconds"]
            output["serve_stale"] = policy["serve_stale"]
            output["historical_live_age_bypass"] = True
            connection.send_result(msg["id"], output)
            return
        elif action == "historical_select":
            from .opera_ring_buffer import _utc
            stamp = msg.get("stamp", "")
            _utc(stamp)
            pinned = await hass.async_add_executor_job(
                partial(store.pin_verified_original, stamp))
            state["test68_selection"] = pinned
            selected = {"stamp": stamp, "bytes": pinned["bytes"],
                        "sha256": pinned["sha256"],
                        "scientific_status": "UNVERIFIED"}
            storage = await hass.async_add_executor_job(store.snapshot)
            connection.send_result(msg["id"], {
                "schema": "weather_router.opera.historical_selection.v1",
                "frame": selected,
                "storage": storage,
                "scientific_status": "UNVERIFIED",
                "historical_tile_authorized": False,
                "tile_url": None,
            })
            return
        elif action == "cleanup":
            await hass.async_add_executor_job(store.cleanup)
        elif action == "clear":
            if msg.get("confirm") is not True:
                raise ValueError("confirmation_required")
            if monitor is not None:
                await monitor.stop()
            try:
                await hass.async_add_executor_job(partial(store.clear, confirmed=True))
            finally:
                # The operator's prior opt-in is preserved even on disk failure.
                if monitor is not None and monitor.enabled:
                    await monitor.start()
        storage = await hass.async_add_executor_job(store.snapshot)
        from .opera_preview_age_policy import preview_continuity_from_entries
        entries = hass.config_entries.async_entries(DOMAIN)
        policy = preview_continuity_from_entries(entries)
        preview_enabled = any(
            entry.options.get("opera_dev_preview_enabled") is True
            for entry in entries)
        frames = await hass.async_add_executor_job(store.list_frames)
        from .opera_config import service_allowed
        options = entries[0].options if entries else {}
        stage = hass.data.get(DOMAIN, {}).get("opera_rate_delivery", {})
        registry = stage.get("registry")
        delivery_state = (registry.delivery_state(
            enabled=(options.get(CONF_ROUTER_ENABLED, True) is True
                     and "opera" in options.get(CONF_ENABLED_PROVIDERS, ())
                     and service_allowed(options, "RATE") and stage.get("enabled") is True),
            max_age_seconds=policy["delivery_limit_seconds"]) if registry is not None else {})
        connection.send_result(msg["id"], {
            "schema": "weather_router.opera.ring.admin.v1",
            "version": DEV_BUILD_VERSION,
            "loader": DEV_LOADER_REV,
            "storage": storage, "frames": frames[-48:],
            "preview_settings": {
                "preview_enabled": preview_enabled,
                "configured_max_age_seconds": policy["freshness_seconds"],
                "effective_max_age_seconds": policy["delivery_limit_seconds"],
                "stale_after_seconds": policy["stale_after_seconds"],
                "serve_stale": policy["serve_stale"],
                "scientific_approval": False,
            },
            "rate_delivery": {
                "last_stage": state.get("last_rate_stage"),
                "registered_stamp": getattr(
                    state.get("rate_bridge"), "last_stamp", None),
                "last_error_code": getattr(
                    state.get("rate_bridge"), "last_error", None),
                "scientific_status": "UNVERIFIED",
                "production_tiles_authorized": False,
                "diagnostic_registration_only": True,
                **delivery_state,
                "consumer_v2": hass.data.get(DOMAIN, {}).get("opera_rate_routing"),
            },
            "monitor": monitor.snapshot() if monitor is not None else None,
            "recovery": {"original_count": len(state.get("recovery", {}).get("originals", [])),
                         "removed_temporary": state.get("recovery", {}).get("removed_temporary", 0)}
                         if isinstance(state.get("recovery"), dict) else None,
            "manual_last_download_utc": state.get("manual_last_download_utc"),
            "manual_last_stamp_utc": state.get("manual_last_stamp_utc"),
            "manual_last_store_status": state.get("manual_last_store_status"),
            "scientific_approved": False,
            "historical_tiles_authorized": False,
        })
    except (OSError, ValueError, PermissionError) as exc:
        # Explicit, non-sensitive diagnostic codes for TEST68; never reveal
        # source file paths, native exception messages, or original data.
        safe = {"frame_not_found", "frame_integrity_failed",
                "frame_size_invalid", "frame_hdf5_magic_invalid", "frame_read_incomplete", "invalid_tile_coordinates",
                "historical_frame_changed", "historical_selection_required",
                "historical_frame_unavailable", "historical_frame_integrity_missing",
                "odim_time_mismatch", "georeference_missing", "render_failed",
                "unverified_projection", "invalid_grid", "window_too_large",
                "png_limit", "invalid_historical_hdf5"}
        reason = str(exc) if type(exc) is ValueError and str(exc) in safe else "ring_operation_failed"
        connection.send_error(msg["id"], reason, "OPERA diagnostic operation blocked")


def async_register(hass):
    websocket_api.async_register_command(hass, ws_opera_ring)
