"""Static contract test for the P3-TORNADO-10 inventory."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "p3_tornado_inventory.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
HAZARD_TYPES_PATH = (
    ROOT / "custom_components" / "weather_router" / "consumer_hazard_event_types.json"
)
REGISTRY_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "registry.json"
HAZARD_COMMON_PATH = (
    ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
)


class P3TornadoInventoryContractTest(unittest.TestCase):
    """Keep the P3-TORNADO-10 inventory tied to the real standard core."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.hazard_types = json.loads(HAZARD_TYPES_PATH.read_text(encoding="utf-8"))
        registry_raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.registry = (
            registry_raw if isinstance(registry_raw, list) else registry_raw["providers"]
        )
        cls.hazard_common = HAZARD_COMMON_PATH.read_text(encoding="utf-8")

    def test_no_dedicated_tornado_public_capability_exists(self) -> None:
        public_ids = self.mapping["public_capabilities"]
        dedicated = [
            item
            for item in public_ids
            if "tornado" in item.casefold()
            or "waterspout" in item.casefold()
            or "windhose" in item.casefold()
        ]
        self.assertEqual(dedicated, [])
        self.assertEqual(
            self.inventory["summary"]["dedicated_public_capabilities"],
            0,
        )

    def test_warning_public_path_carries_tornado_and_waterspout(self) -> None:
        public = self.mapping["public_capabilities"]["weather.warning.official"]
        self.assertEqual(public["strategy"], "aggregate")
        self.assertIn("hazard_feed", public["resource_types"])
        self.assertIn("tornado", public["hazard_types"])
        self.assertIn("waterspout", public["hazard_types"])

    def test_warning_candidate_set_is_exactly_dwd_and_nws(self) -> None:
        actual = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if "weather.warning.official" in public_ids:
                    actual.append(f"{provider_id}/{capability_id}")
        self.assertEqual(
            actual,
            [
                "dwd/official_weather_warnings",
                "noaa_nws/official_weather_alerts",
            ],
        )

    def test_stable_hazard_types_exist(self) -> None:
        types = self.hazard_types["hazard_types"]
        self.assertEqual(types["tornado"]["group"], "convective_hazards")
        self.assertEqual(types["waterspout"]["group"], "convective_hazards")

    def test_text_normalization_preserves_tornado_and_waterspout(self) -> None:
        for marker in (
            '("waterspout", ("waterspout", "wasserhose"))',
            '("tornado", ("tornado", "windhose"))',
        ):
            self.assertIn(marker, self.hazard_common)

    def test_dwd_and_nws_are_the_only_registry_tornado_topics(self) -> None:
        actual = [
            item["module"]
            for item in self.registry
            if "tornado" in item.get("topics", [])
        ]
        self.assertEqual(actual, ["dwd", "noaa_nws"])

    def test_no_dedicated_observation_rotation_or_probability_is_inventoried(self) -> None:
        summary = self.inventory["summary"]
        self.assertEqual(summary["dedicated_observation_capabilities"], 0)
        self.assertEqual(summary["dedicated_radar_rotation_capabilities"], 0)
        self.assertEqual(summary["dedicated_probability_capabilities"], 0)
        self.assertEqual(summary["dedicated_watch_or_outlook_public_capabilities"], 0)

    def test_radar_rotation_never_equals_confirmed_tornado(self) -> None:
        boundaries = set(self.inventory["hard_boundaries"])
        self.assertIn(
            "confirmed_tornado_is_not_radar_rotation_signal",
            boundaries,
        )
        self.assertIn(
            "radar_rotation_signal_is_not_thunderstorm_cell",
            boundaries,
        )
        self.assertIn(
            "official_tornado_warning_is_not_confirmed_tornado",
            boundaries,
        )

    def test_planned_sources_do_not_count_as_current_coverage(self) -> None:
        invariants = set(self.inventory["invariants"])
        self.assertIn(
            "Future/planned providers do not count as current coverage.",
            invariants,
        )

    def test_core_routing_invariants_remain_explicit(self) -> None:
        invariants = set(self.inventory["invariants"])
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)


if __name__ == "__main__":
    unittest.main()
