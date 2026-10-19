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
spatial = importlib.import_module(NAME + ".spatial_coverage")


def real_handler_with_stubs(namespace: dict):
    tree = ast.parse((PKG / "consumer_raster_mosaic_api.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body
                    if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "websocket_consumer_resolve_mosaic")
    # Decorators require HA; strip only those, not the handler logic.
    function.decorator_list = []
    # Core imports moved under the V2 deadline; replace imports recursively.
    class StripCoreImports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.level == 1 and node.module in (
                    "consumer_api", "consumer_api_monitor"):
                return ast.copy_location(ast.Pass(), node)
            return node

    function = StripCoreImports().visit(function)
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, function], type_ignores=[]))
    exec(compile(module, str(PKG / "consumer_raster_mosaic_api.py"), "exec"), namespace)
    return namespace["websocket_consumer_resolve_mosaic"]


class FakeConnection:
    def __init__(self):
        self.results = []
        self.errors = []
        self._ticket = {"monitor": True}

    def send_result(self, msg_id, value):
        self.results.append((msg_id, value))

    def send_error(self, msg_id, code, message):
        self.errors.append((msg_id, code, message))


class FakeCapability:
    id = "radar_layer"
    render_mode = "raster_tile"


class FakeProvider:
    def __init__(self, name, coverage, *, enabled=True, crash=False, coverage_delay=0):
        self.id = name
        self.coverage = coverage
        self.enabled = enabled
        self.crash = crash
        self.coverage_delay = coverage_delay
        self.calls = 0
        self.capability = FakeCapability()

    async def async_get_coverage(self, hass, capability):
        self.calls += 1
        if self.coverage_delay:
            await asyncio.sleep(self.coverage_delay)
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
            # The handler AST is tested separately from its module globals.
            "_shared_coverage_slots": lambda: asyncio.Semaphore(3),
            "monitored_connection": lambda hass, connection, msg, version: connection,
            "validate_raster_mosaic_request": validator.validate_raster_mosaic_request,
            "MosaicContractError": validator.MosaicContractError,
            "viewport_overlap": policy.viewport_overlap,
            "normalize_coverage": lambda raw: raw,
            "CoverageTemporarilyUnavailable": spatial.CoverageTemporarilyUnavailable,
            "resolve_mosaic_snapshot": deterministic_mosaic,
            "profile_allows_capability": lambda *args: (True, None),
            "profile_allows_provider": lambda *args: True,
            "profile_allows_candidate": lambda *args: (True, None),
            "MAX_COVERAGE_CONTACTS": 12,
            "MAX_COVERAGE_CONCURRENT": 3,
            "COVERAGE_TIMEOUT_SECONDS": 6.0,
            "MOSAIC_PROVIDER_DEADLINE_SECONDS": 16.0,
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
        self.environment = environment
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

    async def test_transient_coverage_error_does_not_mean_outside_coverage(self):
        async def transient(*args):
            raise spatial.CoverageTemporarilyUnavailable(
                "source metadata is unavailable"
            )
        self.regional.async_get_coverage = transient
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.errors, [])
        report = self.connection._monitor_routing["coverage_preflight"]
        statuses = {row["source_id"]: row["result"] for row in report}
        self.assertEqual(
            statuses["regional_radar/radar_layer"], "temporarily_unavailable"
        )
        self.assertEqual(statuses["wide_world/radar_layer"], "coverage_accepted")
        self.assertNotIn("source metadata is unavailable", repr(report))

    async def test_v2_exposes_selected_and_outside_coverage_in_response(self):
        # The consumer must not need private API-Monitor information to
        # distinguish a genuine bbox miss from delivered layers.
        self.regional.coverage = {"scope": "bbox", "bbox": {
            "west": 60, "south": -40, "east": 80, "north": -20}}
        await self.handler(None, self.connection, request())
        answer = self.connection.results[0][1]
        outcome = {v["source_id"]: v["result"]
                   for v in answer["source_outcomes"]}
        self.assertEqual(outcome["regional_radar/radar_layer"],
                         "outside_coverage")
        self.assertEqual(outcome["wide_world/radar_layer"], "selected")
        self.assertEqual(answer["layer_order"], "background_to_foreground")
        self.assertEqual(
            self.connection._monitor_routing["delivered_sources"],
            ["wide_world/radar_layer"])

    async def test_v2_transient_reason_available_in_public_response(self):
        async def temporary(*args):
            raise spatial.CoverageTemporarilyUnavailable("synthetic WMS issue")
        self.regional.async_get_coverage = temporary
        await self.handler(None, self.connection, request())
        outcome = {v["source_id"]: v["result"]
                   for v in self.connection.results[0][1]["source_outcomes"]}
        self.assertEqual(outcome["regional_radar/radar_layer"],
                         "temporarily_unavailable")
        self.assertEqual(outcome["wide_world/radar_layer"], "selected")
        self.assertNotIn("synthetic WMS issue",
                         repr(self.connection.results[0][1]))

    async def test_v2_timeout_reason_available_in_public_response(self):
        self.regional.coverage_delay = .06
        self.environment["COVERAGE_TIMEOUT_SECONDS"] = .005
        await self.handler(None, self.connection, request())
        outcome = {v["source_id"]: v["result"]
                   for v in self.connection.results[0][1]["source_outcomes"]}
        self.assertEqual(outcome["regional_radar/radar_layer"],
                         "coverage_timeout")
        self.assertEqual(outcome["wide_world/radar_layer"], "selected")

    async def test_old_world_satellite_requires_consent_then_draws_below_radar(self):
        self.rows[1].semantics = {
            "quantity": "precipitation_rate", "unit": "mm/h",
            "measurement_method": "satellite_precipitation_estimate",
            "observation_kind": "estimate",
        }
        async def old_world(*args):
            return {
                "tile_url": "https://example.invalid/{z}/{x}/{y}.png",
                "frame_time": "2026-10-14T08:30:00Z",
                "attribution": "world", "legend": {"title": "world"},
            }
        self.world.async_get_map_layer = old_world
        strict = request()
        await self.handler(None, self.connection, strict)
        answer = self.connection.results[0][1]
        by_source = {r["source_id"]: r["result"]
                     for r in answer["source_outcomes"]}
        self.assertEqual(by_source["wide_world/radar_layer"], "consent_required")
        self.assertEqual(by_source["regional_radar/radar_layer"], "selected")
        self.assertEqual(len(answer["layers"]), 1)

        approved = request()
        approved["time"]["max_background_age_seconds"] = 43200
        self.connection = FakeConnection()
        await self.handler(None, self.connection, approved)
        answer = self.connection.results[0][1]
        self.assertEqual(
            [x["source_id"] for x in answer["layers"]],
            ["wide_world/radar_layer", "regional_radar/radar_layer"])
        self.assertEqual(answer["layers"][0]["freshness_class"],
                         "older_background")
        self.assertEqual(answer["layers"][0]["composition"]["draw_order"], 0)
        self.assertEqual(answer["layers"][1]["composition"]["draw_order"], 1)

    async def test_stale_regional_is_reported_but_world_kept(self):
        async def old_radar(*args):
            return {
                "tile_url": "https://example.invalid/{z}/{x}/{y}.png",
                "frame_time": "2026-10-14T12:00:00Z",
                "attribution": "regional", "legend": {"title": "regional"},
            }
        self.regional.async_get_map_layer = old_radar
        await self.handler(None, self.connection, request())
        answer = self.connection.results[0][1]
        status = {x["source_id"]: x["result"]
                  for x in answer["source_outcomes"]}
        self.assertEqual(status["regional_radar/radar_layer"], "source_stale")
        self.assertEqual(status["wide_world/radar_layer"], "selected")

    async def test_coverage_timeout_is_visible_even_when_nasa_succeeds(self):
        # Reproduce HA: working world source and slow regional WMS coverage.
        self.regional.coverage_delay = .04
        self.environment["COVERAGE_TIMEOUT_SECONDS"] = .005
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.errors, [])
        self.assertEqual([v["source_id"] for v in
                          self.connection.results[0][1]["layers"]],
                         ["wide_world/radar_layer"])
        report = self.connection._monitor_routing["coverage_preflight"]
        self.assertEqual({v["source_id"]: v["result"] for v in report},
                         {"regional_radar/radar_layer": "coverage_timeout",
                          "wide_world/radar_layer": "coverage_accepted"})
        self.assertTrue(all(isinstance(v["duration_ms"], (int, float)) for v in report))
        self.assertNotIn("https", repr(report))

    async def test_slower_regional_coverage_survives_bounded_extra_budget(self):
        self.regional.coverage_delay = .025
        self.environment["COVERAGE_TIMEOUT_SECONDS"] = .10
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.errors, [])
        self.assertEqual(len(self.connection.results[0][1]["layers"]), 2)
        by_source = {v["source_id"]: v["result"] for v in
                     self.connection._monitor_routing["coverage_preflight"]}
        self.assertEqual(by_source["regional_radar/radar_layer"], "coverage_accepted")

    async def test_monitor_separates_slot_wait_from_provider_wait(self):
        self.regional.coverage_delay = .035
        self.world.coverage_delay = .035
        self.environment["_shared_coverage_slots"] = lambda: asyncio.Semaphore(1)
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.errors, [])
        report = self.connection._monitor_routing["coverage_preflight"]
        self.assertEqual(len(report), 2)
        self.assertTrue(all(isinstance(x["slot_wait_ms"], (int, float))
                            for x in report))
        self.assertTrue(all(isinstance(x["provider_wait_ms"], (int, float))
                            for x in report))
        self.assertTrue(any(x["slot_wait_ms"] >= 20 for x in report))
        self.assertTrue(all(x["provider_wait_ms"] >= 25 for x in report))
        self.assertNotIn("https://", repr(report))

    async def test_timeout_shows_safe_provider_stage_only(self):
        self.regional.coverage_delay = .030
        self.environment["COVERAGE_TIMEOUT_SECONDS"] = .006
        self.regional.coverage_preflight_diagnostics = lambda _: {
            "cache_valid": False, "refresh_running": True,
            "lookup_stage": "aggregate_wms",
            "cache_ttl_remaining_seconds": None,
            "unexpected_detail": "omit-this-value",
        }
        await self.handler(None, self.connection, request())
        report = {
            x["source_id"]: x for x in
            self.connection._monitor_routing["coverage_preflight"]
        }
        self.assertEqual(report["regional_radar/radar_layer"]["result"],
                         "coverage_timeout")
        state = report["regional_radar/radar_layer"]["provider_state"]
        self.assertEqual(state["lookup_stage"], "aggregate_wms")
        self.assertTrue(state["refresh_running"])
        self.assertNotIn("unexpected_detail", repr(report))

    async def test_coverage_provider_failure_is_safe_and_distinct(self):
        self.regional.crash = True
        await self.handler(None, self.connection, request())
        report = self.connection._monitor_routing["coverage_preflight"]
        status = {v["source_id"]: v["result"] for v in report}
        self.assertEqual(status["regional_radar/radar_layer"], "coverage_provider_error")
        self.assertEqual(status["wide_world/radar_layer"], "coverage_accepted")

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

    async def test_coverage_budget_uses_core_score_not_catalog_order(self):
        # Twelve lower-ranked candidates precede a better world source.
        # The top-ranked source must still receive a coverage preflight.
        rows = []
        for index in range(12):
            provider = FakeProvider(f"low_{index}", {
                "scope": "bbox",
                "bbox": {"west": 5, "south": 46, "east": 16, "north": 56},
            })
            candidate = FakeCandidate(provider)
            candidate.score = (9, 9, index)
            rows.append(candidate)
        best = FakeCandidate(self.world)
        best.score = (0, 0, 0)
        rows.append(best)
        self.rows[:] = rows
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.errors, [])
        self.assertGreater(self.world.calls, 0)
        result = self.connection.results[0][1]
        self.assertEqual(result["layers"][0]["source_id"], "wide_world/radar_layer")
        self.assertTrue(any("Coverage-Kontaktbudget" in entry
                            for entry in result["limitations"]))

    async def test_disabled_top_ranked_source_never_consumes_coverage_budget(self):
        disabled = FakeProvider("disabled_best", {"scope": "global"}, enabled=False)
        top = FakeCandidate(disabled)
        top.score = (0, 0, 0)
        world = FakeCandidate(self.world)
        world.score = (1, 0, 0)
        self.rows[:] = [top, world]
        await self.handler(None, self.connection, request())
        self.assertEqual(disabled.calls, 0)
        self.assertGreater(self.world.calls, 0)
        self.assertEqual(self.connection.errors, [])
        self.assertEqual(self.connection.results[0][1]["layers"][0]["source_id"],
                         "wide_world/radar_layer")

    async def test_coverage_preflight_never_exceeds_hard_contact_limit(self):
        providers = []
        for index in range(20):
            provider = FakeProvider(f"candidate_{index}", {"scope": "global"})
            candidate = FakeCandidate(provider)
            candidate.score = (index, 0, 0)
            providers.append(candidate)
        self.rows[:] = providers
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.errors, [])
        contacted = sum(candidate.provider.calls > 0 for candidate in providers)
        self.assertEqual(contacted, 12)
        self.assertTrue(all(candidate.provider.calls == 0
                            for candidate in providers[12:]))
        self.assertTrue(any("Coverage-Kontaktbudget" in item
                            for item in self.connection.results[0][1]["limitations"]))

    async def test_duplicate_descriptors_do_not_waste_coverage_contacts(self):
        duplicates = []
        for index in range(12):
            candidate = FakeCandidate(self.regional)
            candidate.score = (index, 0, 0)
            duplicates.append(candidate)
        world = FakeCandidate(self.world)
        world.score = (12, 0, 0)
        self.rows[:] = duplicates + [world]
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.errors, [])
        self.assertEqual(self.regional.calls, 2)
        self.assertEqual(self.world.calls, 2)
        self.assertEqual(
            [layer["source_id"] for layer in self.connection.results[0][1]["layers"]],
            ["wide_world/radar_layer", "regional_radar/radar_layer"],
        )

    async def test_duplicates_alone_do_not_claim_contact_budget_exhausted(self):
        duplicates = []
        for index in range(15):
            candidate = FakeCandidate(self.world)
            candidate.score = (index, 0, 0)
            duplicates.append(candidate)
        self.rows[:] = duplicates
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.errors, [])
        self.assertEqual(self.world.calls, 2)
        limitations = self.connection.results[0][1]["limitations"]
        self.assertFalse(any("Coverage-Kontaktbudget" in item
                             for item in limitations))

    async def test_outside_coverage_does_not_fetch_raster(self):
        outside = FakeProvider("outside", {
            "scope": "bbox",
            "bbox": {"west": 110, "south": -35, "east": 155, "north": -10},
        })
        self.rows[:] = [FakeCandidate(outside), FakeCandidate(self.world)]
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.errors, [])
        self.assertEqual(outside.calls, 1)
        self.assertEqual(self.world.calls, 2)
        self.assertEqual([layer["source_id"]
                          for layer in self.connection.results[0][1]["layers"]],
                         ["wide_world/radar_layer"])

    async def test_many_capabilities_of_one_provider_leave_room_for_world(self):
        # A dozen distinct capabilities from one provider must not exclude
        # a separate authorized global provider from the coverage preflight.
        many = FakeProvider("many_capabilities", {
            "scope": "bbox",
            "bbox": {"west": 5, "south": 46, "east": 16, "north": 56},
        })
        rows = []
        for index in range(12):
            candidate = FakeCandidate(many)
            candidate.capability = types.SimpleNamespace(
                id=f"raster_{index}", render_mode="raster_tile")
            candidate.score = (0, index, 0)
            rows.append(candidate)
        world = FakeCandidate(self.world)
        world.score = (1, 0, 0)
        self.rows[:] = rows + [world]
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.errors, [])
        self.assertEqual(self.world.calls, 2)
        self.assertLessEqual(many.calls, 22)
        self.assertEqual(self.connection.results[0][1]["layers"][0]["source_id"],
                         "wide_world/radar_layer")

    async def test_coverage_concurrency_stays_bounded(self):
        active = 0
        maximum = 0

        class MeasuredProvider(FakeProvider):
            async def async_get_coverage(self, hass, capability):
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                try:
                    await asyncio.sleep(0.005)
                    return await super().async_get_coverage(hass, capability)
                finally:
                    active -= 1

        rows = []
        for index in range(12):
            provider = MeasuredProvider(f"measured_{index}", {"scope": "global"})
            candidate = FakeCandidate(provider)
            candidate.score = (index, 0, 0)
            rows.append(candidate)
        self.rows[:] = rows
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.errors, [])
        self.assertLessEqual(maximum, 3)
        self.assertEqual(sum(row.provider.calls > 0 for row in rows), 12)

    async def test_unavailable_coverage_does_not_fetch_raster(self):
        broken = FakeProvider("broken_coverage", {"scope": "global"}, crash=True)
        self.rows[:] = [FakeCandidate(broken), FakeCandidate(self.world)]
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.errors, [])
        self.assertEqual(broken.calls, 1)
        self.assertEqual(self.world.calls, 2)
        self.assertEqual([layer["source_id"]
                          for layer in self.connection.results[0][1]["layers"]],
                         ["wide_world/radar_layer"])

    async def test_whole_handler_deadline_covers_catalogue_resolution(self):
        cancelled = False

        async def slow_mapping(hass):
            nonlocal cancelled
            try:
                await asyncio.sleep(0.1)
                return {"public_capabilities": {}}
            except asyncio.CancelledError:
                cancelled = True
                raise

        self.handler.__globals__["_async_mapping"] = slow_mapping
        self.handler.__globals__["MOSAIC_PROVIDER_DEADLINE_SECONDS"] = 0.01
        await self.handler(None, self.connection, request())
        self.assertEqual(self.connection.results, [])
        self.assertEqual(self.connection.errors[0][1], "mosaic_timeout")
        self.assertTrue(cancelled)
        self.assertEqual(self.world.calls, 0)

    async def test_invalid_version_rejected_before_network(self):
        wrong = request()
        wrong["contract_version"] = 1
        await self.handler(None, self.connection, wrong)
        self.assertEqual(self.connection.errors[0][1], "invalid_mosaic_request")
        self.assertEqual(self.world.calls, 0)
        self.assertEqual(self.regional.calls, 0)


if __name__ == "__main__":
    unittest.main()
