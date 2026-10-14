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

    def test_provider_contacts_limited_independently_of_candidates(self):
        calls = []
        sources = [source("global", calls=calls)] + [
            source(f"region_{n}", REGION_CUBA, calls=calls) for n in range(10)
        ]
        got = resolve(sources, request(1))
        self.assertLessEqual(len(calls), 3)
        self.assertEqual(len(got["layers"]), 1)
        self.assertTrue(any("Kontaktbegrenzung" in x for x in got["limitations"]))

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
