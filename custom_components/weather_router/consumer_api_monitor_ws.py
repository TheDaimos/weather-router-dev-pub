"""Administrator-only live Consumer API monitor WebSocket interface."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .consumer_api_monitor import get_monitor


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "weather_router/api_monitor/status",
})
@websocket_api.async_response
async def ws_api_monitor_status(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    monitor = get_monitor(hass)
    connection.send_result(msg["id"], {
        "schema": "weather_router.api_monitor.status.v1",
        "recording": monitor.enabled,
        "session_id": monitor.session_id,
        "record_count": len(monitor.query()["entries"]),
        "buffer_bytes": monitor.query()["buffer_bytes"],
        "limits": {
            "max_records": monitor.max_records,
            "max_bytes": monitor.max_bytes,
            "ttl_seconds": monitor.ttl_seconds,
        },
        "allow_locations": monitor.allow_locations,
    })


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "weather_router/api_monitor/configure",
    vol.Required("enabled"): bool,
    vol.Optional("clear", default=False): bool,
    vol.Optional("allow_locations", default=False): bool,
})
@websocket_api.async_response
async def ws_api_monitor_configure(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    monitor = get_monitor(hass)
    monitor.configure(
        enabled=msg["enabled"],
        clear=msg["clear"],
        allow_locations=msg["allow_locations"],
    )
    connection.send_result(msg["id"], {
        "recording": monitor.enabled,
        "session_id": monitor.session_id,
        "record_count": len(monitor.query()["entries"]),
        "allow_locations": monitor.allow_locations,
    })


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "weather_router/api_monitor/query",
    vol.Optional("api_version"): str,
    vol.Optional("consumer"): str,
    vol.Optional("command"): str,
    vol.Optional("capability"): str,
    vol.Optional("provider"): str,
    vol.Optional("result"): str,
    vol.Optional("correlation_id"): str,
    vol.Optional("session_id"): str,
    vol.Optional("search"): str,
    vol.Optional("min_duration_ms"): vol.Coerce(float),
    vol.Optional("max_duration_ms"): vol.Coerce(float),
})
@websocket_api.async_response
async def ws_api_monitor_query(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    filter_keys = ("api_version", "consumer", "command", "capability", "provider",
                   "result", "correlation_id", "session_id", "search",
                   "min_duration_ms", "max_duration_ms")
    filters = {k: msg[k] for k in filter_keys if k in msg}
    connection.send_result(msg["id"], get_monitor(hass).query(**filters))


def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_api_monitor_status)
    websocket_api.async_register_command(hass, ws_api_monitor_configure)
    websocket_api.async_register_command(hass, ws_api_monitor_query)


def async_unload(hass: HomeAssistant) -> None:
    monitor = hass.data.pop("weather_router_api_monitor", None)
    if monitor is not None:
        monitor.configure(enabled=False, clear=True)
