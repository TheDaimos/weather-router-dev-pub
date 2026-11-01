"""P7-010 check ALL real V1 precipitation mappings against nullable V2 semantics.

No real provider contact, only published provider-neutral capability metadata.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components/weather_router"
MAPPING = json.loads((PKG / "consumer_capability_map.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "contracts/p7_010/raster_mosaic.response.v2.proposal.schema.json")
                    .read_text(encoding="utf-8"))


def load(name):
    spec = importlib.util.spec_from_file_location("p7_" + name, PKG / (name + ".py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load("raster_mosaic_adapter")
policy = load("raster_mosaic_policy")
PUBLIC_ID = "weather.precipitation.layer"


class ActualProviderSemantics(unittest.TestCase):
    def test_all_current_precipitation_candidates_without_unit_fabrication(self):
        published = [
            (provider, internal)
            for provider, mapping in MAPPING["providers"].items()
            for internal, public_ids in mapping.items()
            if PUBLIC_ID in public_ids
        ]
        self.assertGreaterEqual(len(published), 4)
        self.assertIn("null", SCHEMA["$defs"]["layer"]["properties"]["semantics"]
                      ["properties"]["unit"]["type"])
        synthetic = []
        unknown_unit = 0
        for provider, internal in published:
            raw = MAPPING["candidate_semantics"][f"{provider}/{internal}"]
            if raw["unit"] is None:
                unknown_unit += 1
            candidate = adapter.make_mosaic_candidate(
                source_id=f"{provider}/{internal}",
                eligible=True,
                machine_coverage={"scope": "global"},
                payload={
                    "tile_url": "https://example.invalid/placeholder/{z}/{x}/{y}.png",
                    "attribution": provider,
                    "legend": {"title": provider},
                },
                semantics=raw,
                data_time="2026-10-14T15:00:00Z",
                retrieved_at="2026-10-14T15:05:00Z",
            )
            self.assertIsNotNone(candidate, f"{provider}/{internal} incorrectly filtered")
            self.assertEqual(candidate["semantics"]["unit"], raw["unit"])
            synthetic.append(candidate)
        self.assertGreaterEqual(unknown_unit, 1,
                                "this test needs real nullable unit coverage")
        result = policy.plan_raster_mosaic(
            synthetic,
            viewport={"west": -180, "south": -70, "east": 180, "north": 70},
            now="2026-10-14T15:05:00Z",
            max_data_age_seconds=900,
            max_time_delta_seconds=180,
            max_layers=min(12, len(synthetic)),
        )
        self.assertEqual(len(result["layers"]), len(synthetic))
        for layer in result["layers"]:
            self.assertEqual(layer["semantics"]["unit"],
                             MAPPING["candidate_semantics"][layer["source_id"]]["unit"])
            self.assertIn(layer["semantics"]["quantity"],
                          ("precipitation_rate", "radar_reflectivity",
                           "precipitation_accumulation_1h"))
        self.assertEqual(sum(x["semantics"]["unit"] is None for x in result["layers"]),
                         unknown_unit)

    def test_invalid_non_null_unit_is_rejected(self):
        raw = {"quantity": "radar_reflectivity", "unit": 7,
               "measurement_method": "radar_reflectivity",
               "observation_kind": "observation"}
        candidate = adapter.make_mosaic_candidate(
            source_id="synthetic_invalid_unit", eligible=True,
            machine_coverage={"scope": "global"},
            payload={"tile_url": "https://example.invalid/tile",
                     "attribution": "synthetic", "legend": {}},
            semantics=raw,
            data_time="2026-10-14T15:00:00Z",
            retrieved_at="2026-10-14T15:05:00Z")
        self.assertIsNone(candidate)


if __name__ == "__main__":
    unittest.main()
