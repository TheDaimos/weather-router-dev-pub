"""Static contract test for the P3-HAIL-10 inventory."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "p3_hail_inventory.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
DRAFT_MAP_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
HAZARD_TYPES_PATH = (
    ROOT / "custom_components" / "weather_router" / "consumer_hazard_event_types.json"
)
REGISTRY_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "registry.json"
HAZARD_COMMON_PATH = (
    ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
)
DWD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "dwd.py"
NWS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_nws.py"


class P3HailInventoryContractTest(unittest.TestCase):
    """Keep the P3-HAIL-10 inventory tied to the real standard core."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.draft_mapping = json.loads(DRAFT_MAP_PATH.read_text(encoding="utf-8"))
        cls.hazard_types = json.loads(HAZARD_TYPES_PATH.read_text(encoding="utf-8"))
        registry_raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.registry = (
            registry_raw if isinstance(registry_raw, list) else registry_raw["providers"]
        )
        cls.hazard_common = HAZARD_COMMON_PATH.read_text(encoding="utf-8")
        cls.dwd = DWD_PATH.read_text(encoding="utf-8")
        cls.nws = NWS_PATH.read_text(encoding="utf-8")

    def test_no_dedicated_hail_public_capability_exists(self) -> None:
        for mapping in (self.mapping, self.draft_mapping):
            public_ids = mapping["public_capabilities"]
            dedicated = [
                item
                for item in public_ids
                if "hail" in item.casefold() or "hagel" in item.casefold()
            ]
            self.assertEqual(dedicated, [])
        self.assertEqual(
            self.inventory["summary"]["dedicated_public_capabilities"],
            0,
        )

    def test_warning_public_path_carries_hail(self) -> None:
        public = self.mapping["public_capabilities"]["weather.warning.official"]
        self.assertEqual(public["strategy"], "aggregate")
        self.assertIn("hazard_feed", public["resource_types"])
        self.assertIn("hail", public["hazard_types"])

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

    def test_stable_hail_hazard_type_exists(self) -> None:
        hail = self.hazard_types["hazard_types"]["hail"]
        self.assertEqual(hail["group"], "convective_hazards")
        self.assertEqual(hail["name"], "Hagel")

    def test_text_normalization_contains_hail_and_hagel(self) -> None:
        self.assertIn('("hail", ("hail", "hagel"))', self.hazard_common)

    def test_current_normalizer_is_single_label_and_thunderstorm_precedes_hail(self) -> None:
        self.assertIn("return hazard_type", self.hazard_common)
        severe_pos = self.hazard_common.index('"severe_thunderstorm"')
        hail_pos = self.hazard_common.index('("hail", ("hail", "hagel"))')
        self.assertLess(severe_pos, hail_pos)
        self.assertEqual(
            self.inventory["hazard_normalization"]["current_model"],
            "single_label_first_match",
        )
        self.assertEqual(
            self.inventory["hazard_normalization"]["ordering_observation"],
            "severe_thunderstorm_precedes_hail",
        )

    def test_dwd_and_nws_are_the_only_registry_hail_topics(self) -> None:
        actual = [
            item["module"]
            for item in self.registry
            if "hail" in item.get("topics", [])
        ]
        self.assertEqual(actual, ["dwd", "noaa_nws"])

    def test_both_provider_descriptions_explicitly_name_hail(self) -> None:
        self.assertIn("Hagel", self.dwd)
        self.assertIn("Hagel", self.nws)
        for provider in self.inventory["providers"]:
            self.assertTrue(provider["capability_explicit_hail_text"])

    def test_no_dedicated_hail_measurement_contract_is_inventoried(self) -> None:
        summary = self.inventory["summary"]
        self.assertEqual(summary["dedicated_observation_public_capabilities"], 0)
        self.assertEqual(summary["dedicated_hail_size_public_capabilities"], 0)
        self.assertEqual(summary["dedicated_probability_public_capabilities"], 0)
        self.assertEqual(summary["dedicated_radar_hail_signature_public_capabilities"], 0)

    def test_core_routing_invariants_remain_explicit(self) -> None:
        invariants = set(self.inventory["invariants"])
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)
        self.assertIn(
            "P3-HAIL-10 does not change runtime normalization ordering.",
            invariants,
        )


if __name__ == "__main__":
    unittest.main()
