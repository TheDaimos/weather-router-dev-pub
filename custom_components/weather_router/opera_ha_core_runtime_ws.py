"""Administrator-only read-only native audit executed by Home Assistant Core.

The handler itself does not import native packages on HA's event loop: the
blocking checks run inside the Home Assistant executor.
"""
from __future__ import annotations

import platform
import sys
import sysconfig

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .opera_runtime_dependencies import inspect_rate_runtime
from .opera_ha_dev_gate import evaluate_dev_runtime


def _core_snapshot() -> dict:
    packages = inspect_rate_runtime()
    return {
        "target": "HA_DEV_VM109_read_only",
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "architecture": platform.machine(),
        "python_abi": sysconfig.get_config_var("SOABI") or "unknown",
        "platform_tag": sysconfig.get_platform(),
        "libc": platform.libc_ver()[0] or "unknown",
        "package_imports": packages,
        "native_delivery_approved": False,
    }


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "weather_router/opera/dev_runtime_check",
    vol.Required("expected_python"): str,
    vol.Required("expected_architecture"): str,
    vol.Required("expected_abi"): str,
})
@websocket_api.async_response
async def ws_opera_dev_runtime_check(hass: HomeAssistant, connection, msg: dict) -> None:
    """Audit real Core interpreter, not SSH addon or host interpreter."""
    from .const import DOMAIN
    entries = hass.config_entries.async_entries(DOMAIN)
    if len(entries) != 1:
        connection.send_error(msg["id"], "integration_not_ready", "WeatherRouter Config Entry missing")
        return
    # Admin is necessary but insufficient: require explicit operator-known
    # expected ABI values; cannot silently approve a self-reported baseline.
    expected = (msg["expected_python"], msg["expected_architecture"], msg["expected_abi"])
    if any(not value or len(value) > 128 or value != value.strip() for value in expected):
        connection.send_error(msg["id"], "invalid_baseline", "Expected runtime baseline required")
        return
    try:
        snapshot = await hass.async_add_executor_job(_core_snapshot)
        decision = evaluate_dev_runtime(
            snapshot, expected_python=expected[0],
            expected_architecture=expected[1], expected_abi=expected[2])
    except Exception:
        connection.send_error(msg["id"], "native_probe_failed", "Native runtime probe could not complete")
        return
    connection.send_result(msg["id"], {
        "schema": "weather_router.opera.ha_core_runtime.v1",
        "execution_context": "home_assistant_core_executor",
        "runtime": snapshot,
        "decision": decision,
        "vm109_identity_independently_verified": False,
        "installation_approved": False,
        "warning": "Core interpreter observed; VM109 identity and wheel provenance require independent operator verification",
        "scientific_raster_approved": False,
        "package_install_performed": False,
        "diagnostic_frame_registered": False,
    })


def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_opera_dev_runtime_check)
