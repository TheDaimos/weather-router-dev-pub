"""Static contract tests for catalog-wide physical quantity semantics."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
ROUTING_POLICY_PATH = ROOT / "custom_components" / "weather_router" / "consumer_routing_policy.py"
CONSUMER_API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"


class PhysicalSemanticsContractTest(unittest.TestCase):
    """P1-040 makes numeric interchangeability explicit without guessing units."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_runtime_and_contract_maps_match(self) -> None:
        self.assertEqual(self.payload, self.contract)

    def test_every_internal_capability_has_physical_semantics(self) -> None:
        providers = self.payload["providers"]
        physical = self.payload["capability_physical_semantics"]
        assignments = physical["providers"]

        self.assertEqual(
            physical["schema"],
            "weather_router.consumer.capability_physical_semantics.v1",
        )
        self.assertEqual(
            set(physical["unit_sources"]),
            {"provider_capability", "not_applicable"},
        )
        self.assertEqual(set(assignments), set(providers))

        numeric = 0
        non_numeric = 0
        for provider_id, capabilities in providers.items():
            self.assertEqual(set(assignments[provider_id]), set(capabilities), provider_id)
            for capability_id in capabilities:
                item = assignments[provider_id][capability_id]
                if item["numeric"]:
                    numeric += 1
                    self.assertIsInstance(item["quantity"], str)
                    self.assertTrue(item["quantity"])
                    self.assertNotEqual(item["quantity"], "unspecified")
                    self.assertEqual(item["unit_source"], "provider_capability")
                else:
                    non_numeric += 1
                    self.assertIsNone(item["quantity"])
                    self.assertEqual(item["unit_source"], "not_applicable")

        self.assertEqual(numeric, 199)
        self.assertEqual(non_numeric, 81)
        self.assertEqual(numeric + non_numeric, 280)

    def test_explicit_pilot_quantities_match_normalized_contract(self) -> None:
        physical = self.payload["capability_physical_semantics"]["providers"]
        explicit = self.payload.get("candidate_semantics", {})
        for key, item in explicit.items():
            provider_id, capability_id = key.split("/", 1)
            normalized = physical[provider_id][capability_id]
            self.assertTrue(normalized["numeric"], key)
            self.assertEqual(item["quantity"], normalized["quantity"], key)

    def test_reference_quantities_are_distinct_where_physics_differs(self) -> None:
        physical = self.payload["capability_physical_semantics"]["providers"]

        self.assertEqual(
            physical["dwd"]["radar_precipitation_quality_checked"]["quantity"],
            "precipitation_rate",
        )
        self.assertEqual(
            physical["rainviewer"]["radar_reflectivity"]["quantity"],
            "radar_reflectivity",
        )
        self.assertEqual(
            physical["dwd"]["icon_eu_precipitation_1h"]["quantity"],
            "precipitation_accumulation_1h",
        )
        self.assertEqual(
            physical["met_norway"]["nowcast_precipitation"]["quantity"],
            "precipitation_amount",
        )
        self.assertEqual(
            physical["fmi_lightning"]["lightning_nearest_distance"]["quantity"],
            "distance",
        )
        self.assertEqual(
            physical["nasa_iss"]["iss_earth_live"]["unit_source"],
            "not_applicable",
        )

    def test_runtime_uses_provider_unit_contract_and_no_display_text_guessing(self) -> None:
        policy = ROUTING_POLICY_PATH.read_text(encoding="utf-8")
        api = CONSUMER_API_PATH.read_text(encoding="utf-8")

        self.assertIn('physical_all = mapping.get("capability_physical_semantics", {})', policy)
        self.assertIn('raw_unit = raw.get("unit", unit)', policy)
        self.assertIn('unit_source == "not_applicable"', policy)
        self.assertIn('"not_applicable"', policy)
        self.assertIn("candidate quantity drift", api)


if __name__ == "__main__":
    unittest.main()
