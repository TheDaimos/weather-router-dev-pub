"""WR-01: exercise the real DWD WMS/coverage functions without Home Assistant.

Slow first-time GetCapabilities must not be duplicated or cancelled by three
independent six-second V2 coverage budgets. Coverage itself must stay proven
from the actual layer-specific XML bbox. No real HA acceptance is claimed.
"""
from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import time
import types
import unittest
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components/weather_router"
DWD = PACKAGE / "providers/dwd.py"
tree = ast.parse(DWD.read_text(encoding="utf-8"))
functions = {
    node.name: node for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
provider = next(node for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == "DwdProvider")
methods = {
    node.name: node for node in provider.body
    if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
}
wanted = (
    "_local_name",
    "_capabilities_cache_diagnostic",
    "_cached_coverage_result",
    "_parse_wms_document",
    "_wms_layer_coverage",
    "_wms_named_layers",
    "_layer_coverage_cache_diagnostic",
    "_named_layer_names",
    "_shared_global_wms_root",
    "_async_global_wms_coverage",
    "_cached_coverage_result",
    "_observe_background_result",
    "_fetch_capabilities_uncached",
    "_async_capabilities",
)
module = ast.fix_missing_locations(ast.Module(
    body=[
        ast.ImportFrom(module="__future__",
                       names=[ast.alias(name="annotations")], level=0),
        *(functions[name] for name in wanted),
        methods["async_get_coverage"],
        methods["_start_coverage_lookup"],
        methods["_schedule_coverage_refresh"],
        methods["coverage_preflight_diagnostics"],
        methods["_async_get_coverage_uncached"],
    ], type_ignores=[],
))
spatial_spec = importlib.util.spec_from_file_location(
    "wr01_real_spatial_coverage", PACKAGE / "spatial_coverage.py")
assert spatial_spec and spatial_spec.loader
spatial = importlib.util.module_from_spec(spatial_spec)
spatial_spec.loader.exec_module(spatial)

LAYERS = ("Niederschlagsradar", "RADOLAN-RY", "Icon-eu_reg00625_fd_sl_TOTPREC01H")
CAPABILITIES = {
    "radar_precipitation": "Niederschlagsradar",
    "radar_precipitation_quality_checked": "RADOLAN-RY",
    "icon_eu_precipitation_1h": "Icon-eu_reg00625_fd_sl_TOTPREC01H",
}
WMS_XML = (
    '<WMS_Capabilities xmlns="http://www.opengis.net/wms" version="1.3.0">'
    '<Capability><Layer>'
    + "".join(
        '<Layer><Name>' + layer + '</Name><EX_GeographicBoundingBox>'
        '<westBoundLongitude>2</westBoundLongitude>'
        '<eastBoundLongitude>17</eastBoundLongitude>'
        '<southBoundLatitude>46</southBoundLatitude>'
        '<northBoundLatitude>56</northBoundLatitude>'
        '</EX_GeographicBoundingBox></Layer>'
        for layer in LAYERS
    ) + '</Layer></Capability></WMS_Capabilities>'
).encode("utf-8")
NO_BBOX_XML = (
    '<WMS_Capabilities xmlns="http://www.opengis.net/wms" version="1.3.0">'
    '<Capability><Layer>' +
    "".join('<Layer><Name>' + layer + '</Name></Layer>' for layer in LAYERS) +
    '</Layer></Capability></WMS_Capabilities>'
).encode("utf-8")


class Response:
    def __init__(self, session, endpoint):
        self.session = session
        self.endpoint = endpoint
        self.status = 200
        self.headers = {"Content-Type": "text/xml"}

    async def __aenter__(self):
        await asyncio.sleep(self.session.delay)
        if self.session.fail:
            raise OSError("simulated unreachable official WMS")
        return self

    async def __aexit__(self, *args):
        return False

    async def read(self):
        if not self.session.aggregate_has_bbox and not self.endpoint.endswith("/ows"):
            return NO_BBOX_XML
        return WMS_XML

    def raise_for_status(self):
        return None


class Session:
    def __init__(self, *, delay=.045, fail=False, aggregate_has_bbox=True):
        self.delay = delay
        self.fail = fail
        self.aggregate_has_bbox = aggregate_has_bbox
        self.calls = []

    def get(self, base, *, params, timeout):
        self.calls.append((base, params["request"], timeout))
        return Response(self, base)


def harness(session):
    ns = {
        "asyncio": asyncio,
        "monotonic": time.monotonic,
        "datetime": datetime,
        "timezone": timezone,
        "ET": ET,
        "urlsplit": urlsplit,
        "async_get_clientsession": lambda hass: session,
        "_PRIMARY_WMS": "https://primary.invalid/wms",
        "_BACKUP_WMS": "https://backup.invalid/wms",
        "_PRIMARY_GLOBAL_WMS": "https://primary.invalid/ows",
        "_BACKUP_GLOBAL_WMS": "https://backup.invalid/ows",
        "_global_wms_cache": {},
        "_global_wms_inflight_loop": None,
        "_global_wms_inflight": {},
        "_REQUEST_TIMEOUT_SECONDS": 20,
        "_CAPABILITIES_TTL_SECONDS": 300.0,
        "_COVERAGE_REFRESH_LEAD_SECONDS": 90.0,
        "_COVERAGE_REFRESH_RETRY_SECONDS": 30.0,
        "_cached_root": None,
        "_cached_wms_base": None,
        "_cache_valid_until": 0.0,
        "_cache_loaded_at": 0.0,
        "_capabilities_inflight_loop": None,
        "_capabilities_inflight": None,
        "_coverage_inflight_loop": None,
        "_coverage_inflight": {},
        "_coverage_result_cache": {},
        "_coverage_refresh_last_started": {},
        "_coverage_failure_retry_until": {},
        "_coverage_lookup_stage": {},
        "_coverage_refresh_handles": {},
        "_coverage_refresh_next_at": {},
        "_coverage_last_verified_at": {},
        "_coverage_last_refresh_reason": {},
        "_dwd_wms_fetch_phases": {},
        "_layer_coverage_cache": {},
        "_CAPABILITY_MAP": {
            cap: types.SimpleNamespace(layer=layer)
            for cap, layer in CAPABILITIES.items()
        },
        "wms_layer_geographic_coverage": spatial.wms_layer_geographic_coverage,
    }
    exec(compile(module, str(DWD), "exec"), ns)
    # These helpers are needed only if actual metadata has no geographic bbox.
    ns["_async_layer_specific_coverage"] = lambda *args, **kw: None
    cls = type("DwdUnderTest", (), {
        "async_get_coverage": ns["async_get_coverage"],
        "_start_coverage_lookup": ns["_start_coverage_lookup"],
        "_schedule_coverage_refresh": ns["_schedule_coverage_refresh"],
        "coverage_preflight_diagnostics": ns["coverage_preflight_diagnostics"],
        "_async_get_coverage_uncached": ns["_async_get_coverage_uncached"],
    })
    return ns, cls()


class DwdCoverageReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_layer_preflights_share_single_remote_capabilities(self):
        session = Session(delay=.045)
        namespace, provider = harness(session)

        # V2 callers time out first, but must not kill the shared metadata work.
        results = await asyncio.gather(*(
            asyncio.wait_for(provider.async_get_coverage(None, cap), timeout=.008)
            for cap in CAPABILITIES
        ), return_exceptions=True)
        self.assertTrue(all(isinstance(x, TimeoutError) for x in results))
        self.assertEqual(len(session.calls), 1)

        await asyncio.sleep(.06)
        self.assertEqual(len(session.calls), 1)
        for cap in CAPABILITIES:
            coverage = await provider.async_get_coverage(None, cap)
            self.assertEqual(coverage["bbox"],
                             {"west": 2.0, "south": 46.0, "east": 17.0, "north": 56.0})
            self.assertTrue(coverage["cache"]["hit"])
            self.assertEqual(coverage["scope"], "bbox")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(len(namespace["_coverage_result_cache"]), 3)

    async def test_same_layer_reuses_one_task_while_first_caller_cancels(self):
        session = Session(delay=.040)
        _, provider = harness(session)
        tasks = [
            asyncio.create_task(provider.async_get_coverage(None, "radar_precipitation"))
            for _ in range(5)
        ]
        await asyncio.sleep(.005)
        tasks[0].cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self.assertIsInstance(results[0], asyncio.CancelledError)
        self.assertTrue(all(isinstance(x, dict) for x in results[1:]))
        self.assertEqual(len(session.calls), 1)

    async def test_shared_global_fallback_preserves_actual_layer_bbox(self):
        # The DWD aggregate document can omit explicit layer bbox metadata.
        # Three distinct DWD sources must share one fallback document.
        session = Session(delay=.035, aggregate_has_bbox=False)
        namespace, provider = harness(session)
        first = await asyncio.gather(*(
            asyncio.wait_for(provider.async_get_coverage(None, cap), timeout=.009)
            for cap in CAPABILITIES
        ), return_exceptions=True)
        self.assertTrue(all(isinstance(item, TimeoutError) for item in first))
        await asyncio.sleep(.105)
        by_layer = [await provider.async_get_coverage(None, cap)
                    for cap in CAPABILITIES]
        self.assertEqual(len([x for x in session.calls if x[0].endswith("/wms")]), 1)
        self.assertEqual(len([x for x in session.calls if x[0].endswith("/ows")]), 1)
        self.assertTrue(all(x["coverage_metadata_scope"] == "global_wms_layer"
                            for x in by_layer))
        self.assertTrue(all(x["cache"]["hit"] is True for x in by_layer))
        self.assertEqual(len(namespace["_global_wms_cache"]), 1)
        self.assertTrue(all(x["bbox"] == {
            "west": 2.0, "south": 46.0, "east": 17.0, "north": 56.0
        } for x in by_layer))

    async def test_actual_wms_coverage_not_invented_for_cuba(self):
        session = Session(delay=0)
        _, provider = harness(session)
        result = await provider.async_get_coverage(None, "radar_precipitation")
        germany = {"type": "bbox", "west": 7, "east": 12,
                   "south": 48, "north": 55}
        cuba = {"type": "bbox", "west": -85, "east": -75,
                "south": 18, "north": 24}
        self.assertTrue(spatial.coverage_matches_context(result, germany))
        self.assertFalse(spatial.coverage_matches_context(result, cuba))

    async def test_actual_coverage_lookup_runs_in_ha_executor(self):
        class FakeHass:
            def __init__(self):
                self.executions = []

            async def async_add_executor_job(self, function, *args):
                self.executions.append(function.__name__)
                return await asyncio.to_thread(function, *args)

        hass = FakeHass()
        session = Session(delay=0)
        _, provider = harness(session)
        coverage = await provider.async_get_coverage(hass, "radar_precipitation")
        self.assertEqual(coverage["scope"], "bbox")
        self.assertIn("wms_layer_geographic_coverage", hass.executions)

    async def test_idle_viewport_refresh_starts_before_expiry(self):
        session = Session(delay=.008)
        namespace, provider = harness(session)
        # Short scaled TTL, still the same real production method and timer.
        namespace["_CAPABILITIES_TTL_SECONDS"] = .24
        namespace["_COVERAGE_REFRESH_LEAD_SECONDS"] = .16
        namespace["_COVERAGE_REFRESH_RETRY_SECONDS"] = .02
        await asyncio.gather(*(
            provider.async_get_coverage(None, cap) for cap in CAPABILITIES
        ))
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(len(namespace["_coverage_refresh_handles"]), 3)
        # No further consumer requests: real event-loop timers must refresh.
        deadline = time.monotonic() + .70
        while len(session.calls) < 2 and time.monotonic() < deadline:
            await asyncio.sleep(.012)
        self.assertEqual(len(session.calls), 2)
        tasks = list(namespace["_coverage_inflight"].values())
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)
        self.assertTrue(all(
            namespace["_coverage_result_cache"][layer]["valid_until"]
            > time.monotonic()
            for layer in LAYERS
        ))
        self.assertEqual(len(namespace["_coverage_refresh_handles"]), 3)
        # A second autonomous renewal demonstrates repeated cycles.
        deadline = time.monotonic() + .70
        while len(session.calls) < 3 and time.monotonic() < deadline:
            await asyncio.sleep(.012)
        self.assertEqual(len(session.calls), 3)

    async def test_slow_refresh_uses_valid_proof_without_waiting(self):
        session = Session(delay=.035)
        namespace, provider = harness(session)
        await provider.async_get_coverage(None, "radar_precipitation")
        namespace["_coverage_result_cache"]["Niederschlagsradar"][
            "valid_until"
        ] = time.monotonic() + 1.0
        namespace["_cache_valid_until"] = time.monotonic() + 1.0
        task = provider._start_coverage_lookup(
            None, namespace["_CAPABILITY_MAP"]["radar_precipitation"],
            refresh_if_aging=True
        )
        t0 = time.monotonic()
        proof = await provider.async_get_coverage(None, "radar_precipitation")
        self.assertLess(time.monotonic() - t0, .02)
        self.assertTrue(proof["cache"]["hit"])
        self.assertTrue(proof["cache"]["ttl_remaining_seconds"] <= 1)
        self.assertTrue(provider.coverage_preflight_diagnostics(
            "radar_precipitation"
        )["refresh_running"])
        await asyncio.wait_for(task, timeout=1.0)
        self.assertGreater(
            (await provider.async_get_coverage(None, "radar_precipitation"))[
                "cache"]["ttl_remaining_seconds"], 250
        )

    async def test_timer_is_replaced_not_accumulated_on_refresh(self):
        session = Session(delay=.001)
        namespace, provider = harness(session)
        await provider.async_get_coverage(None, "radar_precipitation")
        first = namespace["_coverage_refresh_handles"]["Niederschlagsradar"]
        namespace["_coverage_result_cache"]["Niederschlagsradar"][
            "valid_until"
        ] = time.monotonic() + 1.0
        await provider._start_coverage_lookup(
            None, namespace["_CAPABILITY_MAP"]["radar_precipitation"],
            refresh_if_aging=True
        )
        second = namespace["_coverage_refresh_handles"]["Niederschlagsradar"]
        self.assertIsNot(first, second)
        self.assertTrue(first.cancelled())
        self.assertFalse(second.cancelled())
        self.assertEqual(len(namespace["_coverage_refresh_handles"]), 1)

    async def test_preexpiry_background_refresh_avoids_six_second_cache_gap(self):
        session = Session(delay=.028)
        namespace, provider = harness(session)
        for cap in CAPABILITIES:
            await provider.async_get_coverage(None, cap)
        self.assertEqual(len(session.calls), 1)

        # The aggregate provider document and the three verified layer proofs
        # approach their hard TTL concurrently, reproducing the HA transition.
        approaching = time.monotonic() + 1.5
        namespace["_cache_valid_until"] = approaching
        for layer in LAYERS:
            namespace["_coverage_result_cache"][layer]["valid_until"] = approaching

        t0 = time.monotonic()
        hits = await asyncio.gather(*(
            provider.async_get_coverage(None, cap) for cap in CAPABILITIES
        ))
        self.assertLess(time.monotonic() - t0, .2)
        self.assertTrue(all(x["cache"]["hit"] for x in hits))
        self.assertTrue(all(x["cache"]["ttl_remaining_seconds"] <= 1.5 for x in hits))
        # Await the real background tasks, not a runner-dependent fixed sleep.
        # Under loaded CI the thread executor may not be scheduled immediately.
        refreshes = [namespace["_coverage_inflight"][layer] for layer in LAYERS]
        await asyncio.wait_for(asyncio.gather(*refreshes), timeout=3.0)
        self.assertEqual(len(session.calls), 2, "refresh must be shared")
        for cap in CAPABILITIES:
            recent = await provider.async_get_coverage(None, cap)
            self.assertGreater(recent["cache"]["ttl_remaining_seconds"], 250.0)
            self.assertTrue(recent["cache"]["hit"])

    async def test_cold_cache_state_tracks_real_inflight_stage(self):
        session = Session(delay=.045)
        _, provider = harness(session)
        task = asyncio.create_task(
            provider.async_get_coverage(None, "radar_precipitation")
        )
        await asyncio.sleep(.005)
        detail = provider.coverage_preflight_diagnostics("radar_precipitation")
        self.assertFalse(detail["cache_valid"])
        self.assertTrue(detail["refresh_running"])
        self.assertEqual(detail["lookup_stage"], "aggregate_wms")
        self.assertNotIn("https", repr(detail))
        await task
        after = provider.coverage_preflight_diagnostics("radar_precipitation")
        self.assertTrue(after["cache_valid"])
        self.assertFalse(after["refresh_running"])

    async def test_expired_proof_is_never_accepted_after_failed_refresh(self):
        session = Session(delay=.002)
        namespace, provider = harness(session)
        original = await provider.async_get_coverage(None, "radar_precipitation")
        self.assertEqual(original["scope"], "bbox")
        past = time.monotonic() - 1
        namespace["_coverage_result_cache"]["Niederschlagsradar"]["valid_until"] = past
        namespace["_cache_valid_until"] = past
        session.fail = True
        with self.assertRaises(ValueError):
            await provider.async_get_coverage(None, "radar_precipitation")
        first_attempts = len(session.calls)
        with self.assertRaises(ValueError):
            await provider.async_get_coverage(None, "radar_precipitation")
        self.assertEqual(first_attempts, len(session.calls),
                         "offline retries must be bounded, not a request storm")

    async def test_network_failure_never_becomes_fake_cached_coverage(self):
        session = Session(delay=.001, fail=True)
        namespace, provider = harness(session)
        with self.assertRaises(ValueError):
            await provider.async_get_coverage(None, "radar_precipitation")
        self.assertEqual(namespace["_coverage_result_cache"], {})
        session.fail = False
        # The provider retry throttle blocks hot-looping an unreachable WMS.
        with self.assertRaises(ValueError):
            await provider.async_get_coverage(None, "radar_precipitation")
        namespace["_coverage_failure_retry_until"].clear()
        good = await provider.async_get_coverage(None, "radar_precipitation")
        self.assertEqual(good["scope"], "bbox")
        self.assertGreaterEqual(len(session.calls), 3)


if __name__ == "__main__":
    unittest.main()
