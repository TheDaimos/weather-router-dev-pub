"""P7-010: bounded async service regressions without HA, network or secrets."""
from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components/weather_router"
PSEUDO = "wr_public_p7010_isolated"
if PSEUDO not in sys.modules:
    pkg = types.ModuleType(PSEUDO)
    pkg.__path__ = [str(PKG)]
    sys.modules[PSEUDO] = pkg
service = importlib.import_module(PSEUDO + ".raster_mosaic_service")

TIME = "2026-10-14T15:06:00Z"
REGION_DE = {"scope": "bbox",
             "bbox": {"west": 5, "south": 46, "east": 16, "north": 56}}
REGION_CUBA = {"scope": "bbox",
               "bbox": {"west": -90, "south": 15, "east": -65, "north": 35}}
WORLD = {"scope": "global"}
SEM = {"quantity": "precipitation_rate", "unit": "mm/h",
       "measurement_method": "radar", "observation_kind": "observation"}


def request(layers=3):
    return {"type": "weather_router/consumer/resolve_mosaic",
            "contract_version": 2,
            "capability": "weather.precipitation.layer",
            "context": {"type": "bbox", "west": -90, "south": 15, "east": 8,
                        "north": 56,
                        "focus": {"latitude": 21, "longitude": -76}},
            "time": {"mode": "latest_coherent", "max_data_age_seconds": 900,
                     "max_time_delta_seconds": 180},
            "limits": {"max_layers": layers, "max_tile_requests": 24}}


def source(name, coverage=WORLD, *, enabled=True, calls=None,
           wait=0, fail=False, time=TIME, frames=None):
    async def fetch():
        if calls is not None:
            calls.append(name)
        if wait:
            await asyncio.sleep(wait)
        if fail:
            raise RuntimeError("Synthetic provider outage")
        value = {"tile_url": "https://example.invalid/{z}/{x}/{y}.png",
                 "frame_time": time,
                 "attribution": name,
                 "legend": {"title": name}}
        if frames is not None:
            value["timeline"] = {"frames": frames}
        return value

    return {"source_id": name, "eligible": enabled,
            "machine_coverage": coverage, "semantics": SEM,
            "routing_score": [1, 0, 0], "async_fetch": fetch}


def resolve(sources, user_request=None, **kw):
    return asyncio.run(service.resolve_mosaic_snapshot(
        request() if user_request is None else user_request,
        sources=sources, server_now="2026-10-14T15:08:00Z", **kw))


class RasterMosaicServiceTests(unittest.TestCase):
    def test_opt_in_old_satellite_and_fresh_radar_service_contract(self):
        old = source("world_old", WORLD, time="2026-10-14T08:30:00Z")
        old["semantics"] = {**SEM,
            "measurement_method":"satellite_precipitation_estimate",
            "observation_kind":"estimate"}
        fresh = source("dwd_region", REGION_DE, time="2026-10-14T15:06:00Z")
        query = request()
        strict = resolve([old, fresh], query)
        self.assertEqual([x["source_id"] for x in strict["layers"]], ["dwd_region"])
        query["time"]["max_background_age_seconds"] = 43200
        extended = resolve([old, fresh], query)
        self.assertEqual([x["source_id"] for x in extended["layers"]],
                         ["world_old", "dwd_region"])
        self.assertEqual(extended["layers"][0]["freshness_class"], "older_background")
        self.assertEqual(extended["layers"][1]["freshness_class"], "current")
        self.assertEqual(extended["reference_time"], "2026-10-14T15:06:00Z")

    def test_world_survives_tiny_germany_edge(self):
        got = resolve([source("local_germany", REGION_DE),
                       source("world", WORLD)])
        self.assertEqual([x["source_id"] for x in got["layers"]],
                         ["world", "local_germany"])
        self.assertEqual(got["layers"][1]["coverage"]["west"], 5)
        self.assertEqual(got["status"], "partial")

    def test_prefer_focus_regional_when_budget_is_small(self):
        got = resolve([source("world"), source("germany", REGION_DE),
                       source("focus", REGION_CUBA)], request(2))
        self.assertEqual([x["source_id"] for x in got["layers"]],
                         ["world", "focus"])

    def test_profile_denied_provider_never_contacted(self):
        calls = []
        got = resolve([source("private_disabled", enabled=False, calls=calls),
                       source("world", calls=calls)])
        self.assertEqual(calls, ["world"])
        self.assertEqual([x["source_id"] for x in got["layers"]], ["world"])

    def test_provider_failure_does_not_replace_the_world(self):
        got = resolve([source("world"), source("outage", REGION_CUBA, fail=True)])
        self.assertEqual([x["source_id"] for x in got["layers"]], ["world"])
        self.assertTrue(any("nicht auswertbar" in x for x in got["limitations"]))

    def test_timeout_is_bounded(self):
        got = resolve([source("world"), source("slow", REGION_CUBA, wait=.04)],
                      fetch_timeout_seconds=.001)
        self.assertEqual([x["source_id"] for x in got["layers"]], ["world"])

    def test_provider_contacts_limited_independently_of_render_layers(self):
        calls = []
        sources = [source("global", calls=calls)] + [
            source(f"region_{n}", REGION_CUBA, calls=calls) for n in range(15)
        ]
        got = resolve(sources, request(1))
        # One composited layer must not limit discovery to three providers.
        self.assertEqual(len(calls), service.MAX_CANDIDATE_CONTACTS)
        self.assertEqual(len(got["layers"]), 1)
        self.assertTrue(any("Kontaktbegrenzung" in x for x in got["limitations"]))
        self.assertTrue(any("Ressourcenbegrenzung" in item
                            for item in got["limitations"]))

    def test_twenty_five_candidates_do_not_force_provider_contacts(self):
        calls = []
        # All 25 remain in the trusted inventory; only the explicit contact
        # budget may trigger provider work, independently of max_layers.
        sources = [source("world", WORLD, calls=calls)] + [
            source(f"candidate_{n}", REGION_CUBA, calls=calls)
            for n in range(24)
        ]
        got = resolve(sources, request(1))
        self.assertEqual(len(sources), 25)
        self.assertEqual(len(calls), service.MAX_CANDIDATE_CONTACTS)
        self.assertEqual(len(set(calls)), len(calls))
        self.assertEqual(len(got["layers"]), 1)
        self.assertTrue(any("Kontaktbegrenzung" in note
                            for note in got["limitations"]))

    def test_outside_coverage_candidates_do_not_consume_contacts(self):
        calls = []
        outside = {"scope": "bbox", "bbox": {
            "west": 100, "south": -40, "east": 120, "north": -20}}
        sources = [
            source(f"outside_{n}", outside, calls=calls)
            for n in range(21)
        ] + [source("world", WORLD, calls=calls)]
        got = resolve(sources, request(1))
        self.assertEqual(calls, ["world"])
        self.assertEqual([row["source_id"] for row in got["layers"]], ["world"])

    def test_twelve_spatial_sources_in_one_mosaic(self):
        calls = []
        # One broad foundation plus eleven local envelopes, all eligible.
        sources = [source("world", WORLD, calls=calls)] + [
            source(f"regional_{n}", REGION_CUBA, calls=calls)
            for n in range(11)
        ]
        got = resolve(sources, request(12))
        self.assertEqual(len(calls), 12)
        self.assertEqual(len(got["layers"]), 12)
        self.assertEqual(got["layers"][0]["source_id"], "world")
        self.assertEqual(got["status"], "partial")
        self.assertFalse(any("vorerst auf vier" in item
                             for item in got["limitations"]))

    def test_twelve_descriptors_independent_of_tile_request_budget(self):
        req = request(12)
        req["limits"]["max_tile_requests"] = 3
        got = resolve([source("world", WORLD)] + [
            source(f"regional_{n}", REGION_CUBA) for n in range(11)
        ], req)
        self.assertEqual(len(got["layers"]), 12)
        self.assertTrue(any("Kachelanfragebudget ist getrennt" in item
                            for item in got["limitations"]))

    def test_one_tile_request_does_not_suppress_mosaic_descriptors(self):
        req = request(4)
        req["limits"]["max_tile_requests"] = 1
        got = resolve([source("world", WORLD),
                       source("regional_1", REGION_CUBA),
                       source("regional_2", REGION_DE)], req)
        self.assertEqual(len(got["layers"]), 3)
        self.assertEqual(got["layers"][0]["source_id"], "world")
        self.assertTrue(any("Kachelanfragebudget ist getrennt" in line
                            for line in got["limitations"]))

    def test_never_exceeds_three_simultaneous_contacts(self):
        active = 0
        maximum = 0
        calls = 0

        def make_fetch(name):
            async def fetch():
                nonlocal active, maximum, calls
                active += 1
                calls += 1
                maximum = max(maximum, active)
                await asyncio.sleep(.005)
                active -= 1
                return {"tile_url": "https://example.invalid/{z}/{x}/{y}.png",
                        "frame_time": TIME, "attribution": name,
                        "legend": {"title": name}}
            return fetch

        sources = []
        for index in range(15):
            item = source(f"source_{index}", WORLD if index == 0 else REGION_CUBA)
            item["async_fetch"] = make_fetch(item["source_id"])
            sources.append(item)
        result = resolve(sources, request(4))
        self.assertLessEqual(maximum, service.MAX_PARALLEL_CONTACTS)
        self.assertLessEqual(calls, service.MAX_CANDIDATE_CONTACTS)
        self.assertLessEqual(len(result["layers"]), 4)
        self.assertTrue(any("Kontaktbegrenzung" in line
                            for line in result["limitations"]))

    def test_parallel_consumers_share_global_contact_slots(self):
        async def scenario():
            active = 0
            peak = 0

            async def fetch():
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                try:
                    await asyncio.sleep(.02)
                    return {"tile_url": "https://example.invalid/{z}/{x}/{y}.png",
                            "frame_time": TIME, "attribution": "synthetic",
                            "legend": {"title": "synthetic"}}
                finally:
                    active -= 1

            def inventory(prefix):
                result = []
                for n in range(12):
                    row = source(f"{prefix}_{n}", WORLD if n == 0 else REGION_CUBA)
                    row["async_fetch"] = fetch
                    result.append(row)
                return result

            answers = await asyncio.gather(
                service.resolve_mosaic_snapshot(
                    request(12), sources=inventory("a"),
                    server_now="2026-10-14T15:08:00Z"),
                service.resolve_mosaic_snapshot(
                    request(12), sources=inventory("b"),
                    server_now="2026-10-14T15:08:00Z"))
            return peak, answers

        peak, answers = asyncio.run(scenario())
        self.assertLessEqual(peak, service.MAX_PARALLEL_CONTACTS)
        self.assertEqual(len(answers), 2)
        self.assertTrue(all(len(answer["layers"]) == 12 for answer in answers))

    def test_time_coherent_frame_chosen(self):
        frames = [{"time": "2026-10-14T15:07:00Z",
                   "tile_url": "https://example.invalid/latest.png"},
                  {"time": "2026-10-14T15:01:00Z",
                   "tile_url": "https://example.invalid/near.png"}]
        got = resolve([source("world", time="2026-10-14T15:00:00Z"),
                       source("region", REGION_CUBA, frames=frames)])
        regional = got["layers"][1]
        self.assertEqual(regional["tile_url"], "https://example.invalid/near.png")
        self.assertEqual(regional["times"]["reference_delta_seconds"], 60)

    def test_unsafe_url_rejected_by_adapter(self):
        async def fetch():
            return {"tile_url": "https://example.invalid/tiles?token=private",
                    "frame_time": TIME, "attribution": "untrusted",
                    "legend": {"title": "x"}}
        src = source("not_safe")
        src["async_fetch"] = fetch
        got = resolve([src])
        self.assertEqual(got["layers"], [])

    def test_invalid_v2_request_fails_before_contact(self):
        calls = []
        bad = request()
        bad["contract_version"] = 1
        with self.assertRaises(ValueError):
            resolve([source("world", calls=calls)], bad)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
