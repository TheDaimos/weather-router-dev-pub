"""Static contract test for the P5-SPACE-10 inventory."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "p5_space_inventory.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
REGISTRY_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "registry.json"
SWPC_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_swpc.py"


class P5SpaceInventoryContractTest(unittest.TestCase):
    """Keep P5-SPACE-10 tied to the current standard-core contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["providers"]
        cls.swpc = SWPC_PATH.read_text(encoding="utf-8")

    def _candidates_for(self, public_id: str) -> set[str]:
        result: set[str] = set()
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    result.add(f"{provider_id}/{capability_id}")
        return result

    def test_space_inventory_snapshot_records_32_public_capabilities(self) -> None:
        self.assertEqual(self.inventory["space_public_capability_count"], 32)
        self.assertEqual(
            sum(self.inventory["groups"].values()),
            32,
        )

    def test_current_space_provider_set_and_defaults(self) -> None:
        entries = {item["module"]: item for item in self.registry}
        expected = {
            "noaa_swpc": True,
            "nasa_iss": True,
            "nasa_moon": True,
            "met_norway_astronomy": False,
        }
        for provider, enabled in expected.items():
            self.assertIn(provider, entries)
            self.assertEqual(entries[provider]["default_enabled"], enabled)
            self.assertIn("space", entries[provider]["domains"])

    def test_suvi_wavelengths_are_six_distinct_single_candidates(self) -> None:
        public_ids = [
            "space.solar.suvi.094_angstrom",
            "space.solar.suvi.131_angstrom",
            "space.solar.suvi.171_angstrom",
            "space.solar.suvi.195_angstrom",
            "space.solar.suvi.284_angstrom",
            "space.solar.suvi.304_angstrom",
        ]
        for public_id in public_ids:
            self.assertEqual(len(self._candidates_for(public_id)), 1)
            self.assertTrue(
                next(iter(self._candidates_for(public_id))).startswith("noaa_swpc/")
            )
            self.assertEqual(
                self.mapping["public_capabilities"][public_id]["resource_types"],
                ["image_sequence"],
            )

    def test_non_weather_media_resources_remain_distinct(self) -> None:
        self.assertEqual(
            self.mapping["public_capabilities"]["space.iss.live"]["resource_types"],
            ["live_stream"],
        )
        self.assertEqual(
            self.mapping["public_capabilities"]["space.moon.tiles"]["resource_types"],
            ["planetary_tile"],
        )

    def test_astronomy_values_are_point_value_contracts(self) -> None:
        astronomy_ids = [
            item for item in self.mapping["public_capabilities"]
            if item.startswith("space.moon.") or item.startswith("space.sun.")
        ]
        astronomy_ids.remove("space.moon.tiles")
        self.assertEqual(len(astronomy_ids), 24)
        for public_id in astronomy_ids:
            self.assertEqual(
                self.mapping["public_capabilities"][public_id]["resource_types"],
                ["value"],
            )
            self.assertEqual(len(self._candidates_for(public_id)), 1)
            self.assertTrue(
                next(iter(self._candidates_for(public_id))).startswith(
                    "met_norway_astronomy/"
                )
            )

    def test_inventory_snapshot_records_aurora_as_not_yet_routed(self) -> None:
        aurora = self.inventory["current_aurora_contract"]
        self.assertFalse(aurora["public_capability_present"])
        self.assertTrue(aurora["ovation_provider_service_marker_present"])
        self.assertEqual(aurora["ovation_status"], "vorgemerkt")
        self.assertFalse(aurora["routed_candidate_present"])

    def test_core_invariants_are_explicit(self) -> None:
        invariants = set(self.inventory["invariants"])
        for expected in (
            "Solar EUV imagery is not geomagnetic activity.",
            "Kp index is not local aurora visibility.",
            "Geomagnetic storm is not automatically visible aurora.",
            "Endpoint reachability is not coverage proof.",
            "Provider ID is not a scoring axis.",
            "Profiles remain deny-only.",
        ):
            self.assertIn(expected, invariants)


if __name__ == "__main__":
    unittest.main()
