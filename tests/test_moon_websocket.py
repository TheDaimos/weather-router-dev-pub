"""Execute real Moon WS handler/schema with minimal HA decorator/executor adapters.

This checks the contract and handler, not an installed Home Assistant server.
"""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import voluptuous as vol

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "moon_contract_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "custom_components/weather_router")]
sys.modules[PACKAGE] = package


def websocket_command(schema):
    def decorate(fn):
        fn.schema = vol.Schema({vol.Required("id"): int, **schema})
        return fn
    return decorate


ha = types.ModuleType("homeassistant")
components = types.ModuleType("homeassistant.components")
api = types.ModuleType("homeassistant.components.websocket_api")
api.websocket_command = websocket_command
api.async_response = lambda fn: fn
components.websocket_api = api
core = types.ModuleType("homeassistant.core")
core.HomeAssistant = object
with patch.dict(sys.modules, {"homeassistant": ha, "homeassistant.components": components,
                             "homeassistant.components.websocket_api": api, "homeassistant.core": core}):
    spec = importlib.util.spec_from_file_location(PACKAGE + ".moon_websocket", ROOT / "custom_components/weather_router/moon_websocket.py")
    ws = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ws)


class Executor:
    async def async_add_executor_job(self, fn, *args):
        return await asyncio.to_thread(fn, *args)


class Connection:
    def __init__(self):
        self.results = []
        self.errors = []

    def send_result(self, identifier, result):
        self.results.append((identifier, result))

    def send_error(self, identifier, code, message):
        self.errors.append((identifier, code, message))


def request(**patches):
    return {"id": 42, "type": "weather_router/consumer/moon", "contract_version": 1,
            "latitude": 52.52, "longitude": 13.405, "timestamp_utc": "2024-04-08T18:21:00Z", **patches}


class MoonWebSocketTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_ephemeris_response(self):
        connection = Connection()
        await ws.websocket_moon(Executor(), connection, ws.websocket_moon.schema(request()))
        self.assertEqual(connection.errors, [])
        identifier, data = connection.results[0]
        self.assertEqual(identifier, 42)
        self.assertEqual(data["schema"], "weather_router.moon.v1")
        self.assertEqual(data["phase"], "new_moon")
        self.assertEqual(data["timezone"], "Europe/Berlin")

    def test_contract_validation(self):
        for values in [{"contract_version": 2}, {"latitude": 91}, {"longitude": -181},
                       {"latitude": "invalid"}, {"timestamp_utc": 1}, {"timezone": 1}]:
            with self.assertRaises(vol.Invalid):
                ws.websocket_moon.schema(request(**values))

    async def test_timestamp_zone_and_nan_errors(self):
        for values in [{"timestamp_utc": "invalid"}, {"timestamp_utc": "2024-04-08"},
                       {"timezone": "Invalid/Zone"}, {"latitude": float("nan")},
                       {"timestamp_utc": "2100-01-01T00:00:00Z"}]:
            connection = Connection()
            await ws.websocket_moon(Executor(), connection, request(**values))
            self.assertEqual(connection.results, [])
            self.assertEqual(connection.errors[0][1], "invalid_format")

    async def test_unavailable_dependency(self):
        for exception in (ImportError("missing"), RuntimeError("unavailable")):
            connection = Connection()
            with patch.object(ws, "calculate_moon", side_effect=exception):
                await ws.websocket_moon(Executor(), connection, request())
            self.assertEqual(connection.results, [])
            self.assertEqual(connection.errors[0][1], "moon_unavailable")

    async def test_current_time_default_and_parallel_locations(self):
        current = request()
        current.pop("timestamp_utc")
        connection = Connection()
        await ws.websocket_moon(Executor(), connection, current)
        self.assertEqual(connection.results[0][1]["status"], "ready")
        a, b = Connection(), Connection()
        await asyncio.gather(ws.websocket_moon(Executor(), a, request()),
                             ws.websocket_moon(Executor(), b, request(latitude=-33.87, longitude=151.21)))
        self.assertEqual(a.results[0][1]["timezone"], "Europe/Berlin")
        self.assertEqual(b.results[0][1]["timezone"], "Australia/Sydney")

    def test_registration_and_no_provider_imports(self):
        registration = (ROOT / "custom_components/weather_router/websocket_api.py").read_text(encoding="utf-8")
        self.assertIn("async_register_command(hass, websocket_moon)", registration)
        source = (ROOT / "custom_components/weather_router/moon_engine.py").read_text(encoding="utf-8")
        self.assertNotIn(".providers", source)
        self.assertNotIn(".consumer_api", source)


if __name__ == "__main__":
    unittest.main()
