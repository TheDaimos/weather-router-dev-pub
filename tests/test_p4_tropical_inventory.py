"""Static contract test for the P4-TROPICAL-10 inventory."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "p4_tropical_inventory.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
HAZARD_TYPES_PATH = ROOT / "custom_components" / "weather_router" / "consumer_hazard_event_types.json"
HAZARD_COMMON_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
NHC_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "nhc_tropical_cyclones.py"
GDACS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "gdacs.py"
AVIATION_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "aviation_weather.py"
REGISTRY_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "registry.json"


class P4TropicalInventoryContractTest(unittest.TestCase):
    """Keep P4-TROPICAL-10 tied to the current standard-core contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.hazard_types = json.loads(HAZARD_TYPES_PATH.read_text(encoding="utf-8"))
        cls.hazard_common = HAZARD_COMMON_PATH.read_text(encoding="utf-8")
        cls.nhc = NHC_PATH.read_text(encoding="utf-8")
        cls.gdacs = GDACS_PATH.read_text(encoding="utf-8")
        cls.aviation = AVIATION_PATH.read_text(encoding="utf-8")
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["providers"]

    def test_dedicated_tropical_public_capability_has_only_nhc_candidate(self) -> None:
        target = "natural_hazards.tropical_cyclone.events"
        actual = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if target in public_ids:
                    actual.append(f"{provider_id}/{capability_id}")
        self.assertEqual(actual, ["nhc_tropical_cyclones/active_tropical_cyclones"])
        self.assertEqual(self.inventory["summary"]["dedicated_candidates"], 1)

    def test_dedicated_contract_is_hazard_feed_tropical_cyclone(self) -> None:
        contract = self.mapping["public_capabilities"][
            "natural_hazards.tropical_cyclone.events"
        ]
        self.assertEqual(contract["family"], "tropical_cyclone")
        self.assertEqual(contract["hazard_types"], ["tropical_cyclone"])
        self.assertEqual(contract["resource_types"], ["hazard_feed"])

    def test_nhc_preserves_classification_and_intensity_as_parameters(self) -> None:
        self.assertIn('"hazard_type": "tropical_cyclone"', self.nhc)
        self.assertIn('"classification": classification or None', self.nhc)
        self.assertIn('"intensity_kt": intensity', self.nhc)
        self.assertIn('"pressure_hpa": storm.get("pressure")', self.nhc)

    def test_nhc_has_track_cone_wind_and_surge_resources(self) -> None:
        for marker in (
            '"forecast_track"',
            '"track_cone"',
            '"wind_watches_warnings"',
            '"forecast_wind_radii"',
            '"wind_speed_probabilities"',
            '"storm_surge_watch_warning"',
            '"potential_storm_surge_flooding"',
            '"peak_surge"',
        ):
            self.assertIn(marker, self.nhc)

    def test_nhc_is_default_enabled_and_natural_hazards(self) -> None:
        entry = next(
            item for item in self.registry
            if item.get("module") == "nhc_tropical_cyclones"
        )
        self.assertTrue(entry["default_enabled"])
        self.assertIn("natural_hazards", entry["domains"])

    def test_nhc_inventory_records_regional_not_global_coverage(self) -> None:
        coverage = self.inventory["dedicated_path"]["coverage"]
        self.assertIn("Atlantic", coverage)
        self.assertFalse(
            self.inventory["coverage_gap"]["dedicated_global_primary_coverage"]
        )

    def test_general_weather_warning_can_carry_tropical_cyclone(self) -> None:
        contract = self.mapping["public_capabilities"]["weather.warning.official"]
        self.assertIn("tropical_cyclone", contract["hazard_types"])
        for marker in (
            '"hurricane"',
            '"tropical cyclone"',
            '"tropical storm"',
            '"typhoon"',
        ):
            self.assertIn(marker, self.hazard_common)

    def test_gdacs_tc_is_disaster_awareness_not_primary_authority(self) -> None:
        self.assertIn('"TC": "tropical_cyclone"', self.gdacs)
        path = self.inventory["disaster_awareness_path"]
        self.assertTrue(path["aggregator"])
        self.assertFalse(path["primary_warning_authority"])
        entry = next(item for item in self.registry if item.get("module") == "gdacs")
        self.assertFalse(entry["default_enabled"])

    def test_aviation_paths_remain_aviation_semantics(self) -> None:
        for marker in ('"tc": "tropical_cyclone"', '"tropical cyclone": "tropical_cyclone"'):
            self.assertIn(marker, self.aviation)
        self.assertFalse(
            self.inventory["aviation_semantics"]["general_public_warning"]
        )
        self.assertEqual(len(self.inventory["aviation_paths"]), 3)

    def test_storm_surge_remains_distinct_hydrology_type(self) -> None:
        self.assertEqual(
            self.hazard_types["hazard_types"]["storm_surge"]["group"],
            "hydrology",
        )
        self.assertIn("storm_surge", self.inventory["related_but_distinct"])

    def test_core_invariants_are_explicit(self) -> None:
        invariants = set(self.inventory["invariants"])
        self.assertIn(
            "NHC coverage is not global tropical-cyclone coverage.",
            invariants,
        )
        self.assertIn(
            "GDACS is not a primary tropical-cyclone warning authority.",
            invariants,
        )
        self.assertIn(
            "Aviation SIGMET is not a general public warning.",
            invariants,
        )
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)


if __name__ == "__main__":
    unittest.main()
