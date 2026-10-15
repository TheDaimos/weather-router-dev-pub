"""P7-010 isolated WebSocket handler harness without Home Assistant installation.

Compiles the real handler function after replacing only its relative core import
with controlled stubs. This is NOT a Home Assistant runtime acceptance test.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components/weather_router"
NAME = "wr_public_p7_handler_test"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(PKG)]
    sys.modules[NAME] = package

validator = importlib.import_module(NAME + ".raster_mosaic_contract")
policy = importlib.import_module(NAME + ".raster_mosaic_policy")
service = importlib.import_module(NAME + ".raster_mosaic_service")


def real_handler_with_stubs(namespace: dict):
    tree = ast.parse((PKG / "consumer_raster_mosaic_api.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body
                    if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "websocket_consumer_resolve_mosaic")
    # Decorators require HA; strip only those, not the handler logic.
    function.decorator_list = []
    function.body = [
        ast.Pass() if isinstance(node, ast.ImportFrom)
                      and node.module == "consumer_api" and node.level == 1
        else node
        for node in function.body
    ]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, function], type_ignores=[]))
    exec(compile(module, str(PKG / "consumer_raster_mosaic_api.py"), "exec"), namespace)
    return namespace["websocket_consumer_resolve_mosaic"]


class FakeConnection:
    def __init__(self):
        self.results = []
        self.errors = []

    def send_result(self, msg_id, value):
        self.results.append((msg_id, value))

    def send_error(self, msg_id, code, message):
        self.errors.append((msg_id, code, message))


class FakeCapability:
    id = "radar_layer"
    render_mode = "raster_tile"


class FakeProvider:
    def __init__(self, name, coverage, *, enabled=True, crash=False):
        self.id = name
        self.coverage = coverage
        self.enabled = enabled
        self.crash = crash
        self.calls = 0
        self.capability = FakeCapability()

    async def async_get_coverage(self, hass, capability):
        self.calls += 1
        if self.crash:
            raise RuntimeError("simulated missing machine coverage")
        return self.coverage

    async def async_get_map_layer(self, hass, capability):
        self.calls += 1
        return {"tile_url": "https://example.invalid/{z}/{x}/{y}.png",
                "frame_time": "2026-10-14T15:00:00Z",
                "attribution": self.id, "legend": {"title": self.id}}


class FakeCandidate:
    def __init__(self, provider):
        self.provider = provider
        self.capability = provider.capability
        self.public_id = "weather.precipitation.layer"
        self.score = (1, 0, 0)
        self.semantics = {
            "quantity": "precipitation_rate",
            "unit": "mm/h",
            "measurement_method": "radar",
            "observation_kind": "observation",
        }


class FakeUnavailable(Exception):
    code = "profile_filtered"
    message = "Profile denied"


def request():
    return {
        "id": 42,
        "type": "weather_router/consumer/resolve_mosaic",
        "contract_version": 2,
        "capability": "weather.precipitation.layer",
        "context": {"type": "bbox", "west": -90, "south": 15,
                    "east": 8, "north": 56,
                    "focus": {"latitude": 21, "longitude": -76}},
        "time": {"mode": "latest_coherent", "max_data_age_seconds": 900,
                 "max_time_delta_seconds": 180},
        "limits": {"max_layers": 3, "max_tile_requests": 16},
    }


class WebsocketHarnessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.world = FakeProvider("wide_world", {"scope": "global"})
        self.regional = FakeProvider("regional_radar", {
            "scope": "bbox",
            "bbox": {"west": 5, "south": 46, "east": 16, "north": 56},
        })
        self.rows = [FakeCandidate(self.regional), FakeCandidate(self.world)]
        self.connection = FakeConnection()

        async def async_mapping(hass):
            return {"public_capabilities": {}}

        async def async_providers(hass):
            return {p.provider.id: p.provider for p in self.rows}

        def enabled(state, provider, cap):
            return (provider.enabled, None if provider.enabled else "provider_disabled")

        def normalize(raw):
            return (dict(raw), raw.get("frame_time"))

        async def deterministic_mosaic(query, *, sources):
            # The synthetic October test timestamp must not be compared
            # against the runner's real clock on a later execution day.
            return await service.resolve_mosaic_snapshot(
                query, sources=sources, server_now="2026-10-14T15:08:00Z")

        environment = {
            "asyncio": asyncio,
            "_LIVE_REQUEST_SLOTS": asyncio.Semaphore(2),
            "validate_raster_mosaic_request": validator.validate_raster_mosaic_request,
            "MosaicContractError": validator.MosaicContractError,
            "viewport_overlap": policy.viewport_overlap,
            "normalize_coverage": lambda raw: raw,
            "resolve_mosaic_snapshot": deterministic_mosaic,
            "profile_allows_capability": lambda *args: (True, None),
            "profile_allows_provider": lambda *args: True,
            "profile_allows_candidate": lambda *args: (True, None),
            "MAX_COVERAGE_CONTACTS": 12,
            "MAX_COVERAGE_CONCURRENT": 3,
            "COVERAGE_TIMEOUT_SECONDS": 3.0,
            "CandidateUnavailable": FakeUnavailable,
            "_runtime_state": lambda hass: (
                True, {"router_enabled": True, "enabled_domains": {"weather"},
                       "enabled_providers": {"wide_world", "regional_radar"}}),
            "_async_mapping": async_mapping,
            "_async_providers": async_providers,
            "_validate_mapping_against_providers": lambda *args: None,
            "_profile_for_request": lambda *args: (None, None),
            "_candidate_enabled": enabled,
            "_candidates": lambda providers, mapping, capability: self.rows,
            "_context_supported": lambda *args: True,
            "_coverage_contract_allows": lambda *args: (True, None),
            "_resource_implemented": lambda *args: True,
            "_normalize_raster": normalize,
        }
        self.handler = real_handler_with_stubs(environment)

    async def test_world_plus_regional_from_real_handler_body(self):
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.errors, [])
        self.assertEqual(len(self.connection.results), 1)
        result = self.connection.results[0][1]
        self.assertEqual(result["contract_version"], 2)
        self.assertEqual(result["layers"][0]["source_id"], "wide_world/radar_layer")
        self.assertEqual(result["layers"][1]["source_id"], "regional_radar/radar_layer")
        self.assertEqual(result["layers"][1]["coverage"]["west"], 5)

    async def test_disabled_provider_never_contacts_network(self):
        self.regional.enabled = False
        await self.handler(None, self.connection, request())
        self.assertEqual(self.regional.calls, 0)
        self.assertEqual([x["source_id"] for x in self.connection.results[0][1]["layers"]],
                         ["wide_world/radar_layer"])

    async def test_failing_regional_coverage_does_not_blank_world(self):
        self.regional.crash = True
        await self.handler(None, self.connection, request())
        self.assertEqual(len(self.connection.results[0][1]["layers"]), 1)
        self.assertEqual(self.connection.results[0][1]["layers"][0]["source_id"],
                         "wide_world/radar_layer")

    async def test_invalid_version_rejected_before_network(self):
        wrong = request()
        wrong["contract_version"] = 1
        await self.handler(None, self.connection, wrong)
        self.assertEqual(self.connection.errors[0][1], "invalid_mosaic_request")
        self.assertEqual(self.world.calls, 0)
        self.assertEqual(self.regional.calls, 0)


if __name__ == "__main__":
    unittest.main()
