"""P7-010 synthetic V1-normalized resource -> V2 mosaic response contract.

No provider network, no Home Assistant and no private extension metadata.
"""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components/weather_router"


def load(name: str):
    spec = importlib.util.spec_from_file_location("test_" + name, PKG / (name + ".py"))
    assert spec is not None and spec.loader is not None
    instance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instance)
    return instance


adapter = load("raster_mosaic_adapter")
policy = load("raster_mosaic_policy")
RESPONSE = json.loads((ROOT / "contracts/p7_010/raster_mosaic.response.v2.proposal.schema.json")
                      .read_text(encoding="utf-8"))
WIDE = {"west": -90, "south": 15, "east": 8, "north": 56}
NOW = "2026-10-14T15:08:00Z"
SEM = {
    "quantity": "precipitation_rate",
    "unit": "mm/h",
    "measurement_method": "satellite_estimate",
    "observation_kind": "observation",
}


def source(name: str, coverage: dict, *, enabled: bool = True,
           radar: bool = False, frames: list | None = None):
    payload = {"tile_url": "https://example.invalid/tiles/{z}/{x}/{y}.png",
               "attribution": name, "legend": {"title": name}}
    if frames is not None:
        payload["timeline"] = {"frames": frames}
    return adapter.make_mosaic_candidate(
        source_id=name,
        eligible=enabled,
        machine_coverage=coverage,
        payload=payload,
        semantics={**SEM, "measurement_method": "radar" if radar else "satellite_estimate"},
        data_time="2026-10-14T15:00:00Z",
        retrieved_at=NOW,
    )


def mosaic(*candidates):
    return policy.plan_raster_mosaic(
        [c for c in candidates if c is not None],
        viewport=WIDE,
        focus={"latitude": 21, "longitude": -76},
        now=NOW,
        max_data_age_seconds=900,
        max_time_delta_seconds=180,
        max_layers=4,
    )


class EndToEndContractTests(unittest.TestCase):
    def test_global_and_local_at_matching_time(self):
        global_candidate = source("synthetic_wide", {"scope": "global"})
        local_candidate = source(
            "synthetic_region",
            {"scope": "bbox", "bbox": {"west": 5, "south": 46, "east": 16, "north": 56}},
            radar=True,
            frames=[
                {"time": "2026-10-14T15:06:00Z",
                 "tile_url": "https://example.invalid/latest.png"},
                {"time": "2026-10-14T15:01:00Z",
                 "tile_url": "https://example.invalid/aligned.png"},
            ],
        )
        result = mosaic(local_candidate, global_candidate)
        self.assertEqual(result["contract_version"], 2)
        self.assertEqual(result["status"], "partial")
        self.assertEqual([x["source_id"] for x in result["layers"]],
                         ["synthetic_wide", "synthetic_region"])
        self.assertEqual(result["layers"][1]["tile_url"],
                         "https://example.invalid/aligned.png")
        self.assertEqual(result["layers"][1]["times"]["reference_delta_seconds"], 60)
        self.assertEqual(result["layers"][1]["coverage"]["west"], 5)
        self.assertNotEqual(result["layers"][0]["semantics"]["measurement_method"],
                            result["layers"][1]["semantics"]["measurement_method"])
        required = set(RESPONSE["$defs"]["layer"]["required"])
        for layer in result["layers"]:
            self.assertTrue(required.issubset(layer))
            self.assertIs(layer["coverage_verified"], True)
            self.assertIn(layer["coverage_scope"], {"global", "bbox"})

    def test_provider_opt_out_and_region_only_never_claim_whole_world(self):
        regional = source(
            "regional_only",
            {"scope": "bbox", "bbox": {"west": 5, "south": 46, "east": 16, "north": 56}},
        )
        denied = source("not_enabled", {"scope": "global"}, enabled=False)
        result = mosaic(regional, denied)
        self.assertEqual(len(result["layers"]), 1)
        self.assertEqual(result["layers"][0]["source_id"], "regional_only")
        self.assertTrue(any("Grundversorgung" in x for x in result["limitations"]))

    def test_unknown_coverage_does_not_become_clear_sky(self):
        unknown = source("unverified", {"scope": "unsupported"})
        result = mosaic(unknown)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["layers"], [])


if __name__ == "__main__":
    unittest.main()
