"""Administration-only OPERA product selection, separate from scientific approval."""
from __future__ import annotations
import voluptuous as vol
from homeassistant.components import websocket_api
from .const import DOMAIN, CONF_ENABLED_PROVIDERS, CONF_ROUTER_ENABLED
from .opera_config import read_config, update_config

@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "weather_router/opera/settings",
    vol.Optional("settings"): dict,
})
@websocket_api.async_response
async def ws_opera_settings(hass, connection, msg):
    entries = hass.config_entries.async_entries(DOMAIN)
    if len(entries) != 1:
        connection.send_error(msg["id"], "not_configured", "WeatherRouter not configured")
        return
    entry = entries[0]
    if "settings" in msg:
        try:
            options = update_config(entry.options, msg["settings"])
        except ValueError:
            connection.send_error(msg["id"], "invalid_opera_settings", "Invalid settings")
            return
        hass.config_entries.async_update_entry(entry, options=options)
        ring_state = hass.data.get(DOMAIN, {}).get("opera_ring_buffer", {})
        monitor = ring_state.get("monitor")
        if monitor is not None:
            monitor.enabled = True
            ring_state["monitor_enabled"] = True
            await monitor.start()
        hass.bus.async_fire("weather_router_opera_cycle_available", {
            "provider_id": "opera", "product_id": "RATE", "policy_changed": True,
        })
    settings = read_config(entry.options)
    runtime = hass.data.get(DOMAIN, {}).get("opera_rate_delivery", {})
    registry = runtime.get("registry") if isinstance(runtime, dict) else None
    approved_stamp = registry.current_approved_stamp() if registry is not None else None
    from .opera_preview_age_policy import preview_continuity_from_entries
    state = registry.delivery_state(
        enabled=(entry.options.get(CONF_ROUTER_ENABLED, True) is True
                 and "opera" in entry.options.get(CONF_ENABLED_PROVIDERS, ())
                 and settings["services"]["RATE"] and runtime.get("enabled") is True),
        max_age_seconds=preview_continuity_from_entries(entries)["delivery_limit_seconds"]
    ) if registry is not None else {}
    settings.update(schema="weather_router.opera.settings.v1",
                    provider_enabled=("opera" in entry.options.get(CONF_ENABLED_PROVIDERS, ())
                                      and entry.options.get(CONF_ROUTER_ENABLED, True) is True),
                    raster_approved=approved_stamp is not None,
                    approved_rate_stamp=approved_stamp)
    settings.update({key: value for key, value in state.items() if key != "scientific_status"})
    settings["scientific_status"]["RATE"] = state.get("scientific_status", "NO_ADMITTED_RATE_FRAME")
    connection.send_result(msg["id"], settings)

def async_register(hass):
    websocket_api.async_register_command(hass, ws_opera_settings)
