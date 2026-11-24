"""Authenticated read-only Moon Engine WebSocket, independent of provider routing."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfoNotFoundError

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .moon_engine import calculate_moon


@websocket_api.websocket_command({
    vol.Required("type"): "weather_router/consumer/moon",
    vol.Required("contract_version"): vol.In([1]),
    vol.Required("latitude"): vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
    vol.Required("longitude"): vol.All(vol.Coerce(float), vol.Range(min=-180, max=180)),
    vol.Optional("timestamp_utc"): str,
    vol.Optional("timezone"): str,
})
@websocket_api.async_response
async def websocket_moon(hass: HomeAssistant, connection, msg):
    try:
        stamp = msg.get("timestamp_utc")
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp is not None else datetime.now(timezone.utc)
        result = await hass.async_add_executor_job(
            calculate_moon, msg["latitude"], msg["longitude"], at, msg.get("timezone"))
    except (ValueError, ZoneInfoNotFoundError, OverflowError):
        connection.send_error(msg["id"], "invalid_format", "Invalid coordinate, timestamp or IANA timezone")
        return
    except (ImportError, RuntimeError):
        connection.send_error(msg["id"], "moon_unavailable", "Lunar ephemeris unavailable")
        return
    connection.send_result(msg["id"], result)
