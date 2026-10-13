"""Static contract tests for catalog-wide source semantics."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
ROUTING_POLICY_PATH = ROOT / "custom_components" / "weather_router" / "consumer_routing_policy.py"
CONSUMER_API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"


class SourceSemanticsContractTest(unittest.TestCase):
    """P1-050 separates data origin from measurement/generation method."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_runtime_and_contract_maps_match(self) -> None:
        self.assertEqual(self.payload, self.contract)

    def test_every_internal_capability_has_source_semantics(self) -> None:
        providers = self.payload["providers"]
        source = self.payload["capability_source_semantics"]
        assignments = source["providers"]

        self.assertEqual(
            source["schema"],
            "weather_router.consumer.capability_source_semantics.v1",
        )
        self.assertEqual(set(assignments), set(providers))

        count = 0
        for provider_id, capabilities in providers.items():
            self.assertEqual(set(assignments[provider_id]), set(capabilities), provider_id)
            for capability_id in capabilities:
                item = assignments[provider_id][capability_id]
                for field in ("data_origin", "measurement_method"):
                    self.assertIsInstance(item[field], str)
                    self.assertTrue(item[field])
                    self.assertNotEqual(item[field], "unspecified")
                count += 1

        self.assertEqual(count, 280)

    def test_existing_pilot_semantics_match_normalized_source_contract(self) -> None:
        source = self.payload["capability_source_semantics"]["providers"]
        for key, explicit in self.payload.get("candidate_semantics", {}).items():
            provider_id, capability_id = key.split("/", 1)
            normalized = source[provider_id][capability_id]
            self.assertEqual(explicit["data_origin"], normalized["data_origin"], key)
            self.assertEqual(
                explicit["measurement_method"],
                normalized["measurement_method"],
                key,
            )

    def test_reference_source_classes_are_provider_neutral(self) -> None:
        source = self.payload["capability_source_semantics"]["providers"]

        self.assertEqual(
            source["eccc_geomet"]["temperature"],
            {
                "data_origin": "station",
                "measurement_method": "surface_station_observation",
            },
        )
        self.assertEqual(
            source["usgs_earthquakes"]["earthquakes_past_day"],
            {
                "data_origin": "seismic_network",
                "measurement_method": "seismic_event_catalog",
            },
        )
        self.assertEqual(
            source["gbif_biodiversity"]["occurrence_density_lion"],
            {
                "data_origin": "biodiversity_observation",
                "measurement_method": "occurrence_density_observation",
            },
        )
        self.assertEqual(
            source["eumetsat_mtg_li"]["mtg_li_accumulated_flashes"],
            {
                "data_origin": "satellite",
                "measurement_method": "optical_lightning_detection",
            },
        )
        self.assertEqual(
            source["bbk_mowas"]["civil_protection_warnings_germany"]["data_origin"],
            "warning_authority",
        )

    def test_runtime_uses_static_source_contract_before_unspecified_fallback(self) -> None:
        policy = ROUTING_POLICY_PATH.read_text(encoding="utf-8")
        api = CONSUMER_API_PATH.read_text(encoding="utf-8")
        self.assertIn('source_all = mapping.get("capability_source_semantics", {})', policy)
        self.assertIn('source_semantics.get("data_origin")', policy)
        self.assertIn('source_semantics.get("measurement_method")', policy)
        self.assertIn('for field in ("data_origin", "measurement_method")', api)
        self.assertIn('f"candidate {field} drift for', api)


if __name__ == "__main__":
    unittest.main()
