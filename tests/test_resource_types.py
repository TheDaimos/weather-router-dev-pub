"""Static contract tests for catalog-wide candidate resource types."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
CONSUMER_API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"

ALLOWED = {
    "value",
    "raster_tile",
    "hazard_feed",
    "event_feed",
    "image_sequence",
    "live_stream",
    "planetary_tile",
    "data_file",
}


class ResourceTypeContractTest(unittest.TestCase):
    """P1-030 freezes one machine-readable resource type per internal candidate."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_runtime_and_contract_maps_match(self) -> None:
        self.assertEqual(self.payload, self.contract)

    def test_every_internal_capability_has_exactly_one_resource_type(self) -> None:
        providers = self.payload["providers"]
        contract = self.payload["capability_resource_types"]
        self.assertEqual(
            contract["schema"],
            "weather_router.consumer.capability_resource_types.v1",
        )
        self.assertEqual(set(contract["allowed_resource_types"]), ALLOWED)
        assignments = contract["providers"]
        self.assertEqual(set(assignments), set(providers))

        count = 0
        for provider_id, capabilities in providers.items():
            self.assertEqual(set(assignments[provider_id]), set(capabilities), provider_id)
            for capability_id in capabilities:
                resource_type = assignments[provider_id][capability_id]
                self.assertIn(resource_type, ALLOWED, f"{provider_id}/{capability_id}")
                count += 1

        self.assertEqual(count, 280)

    def test_public_resource_types_equal_candidate_resource_types(self) -> None:
        providers = self.payload["providers"]
        assignments = self.payload["capability_resource_types"]["providers"]
        expected: dict[str, set[str]] = {}

        for provider_id, capabilities in providers.items():
            for capability_id, public_ids in capabilities.items():
                resource_type = assignments[provider_id][capability_id]
                for public_id in public_ids:
                    expected.setdefault(public_id, set()).add(resource_type)

        public = self.payload["public_capabilities"]
        self.assertEqual(set(public), set(expected))
        for public_id, expected_types in expected.items():
            declared = public[public_id].get("resource_types")
            self.assertIsInstance(declared, list, public_id)
            self.assertEqual(set(declared), expected_types, public_id)

    def test_reference_resource_types(self) -> None:
        assignments = self.payload["capability_resource_types"]["providers"]
        self.assertEqual(assignments["open_meteo"]["temperature"], "value")
        self.assertEqual(assignments["dwd"]["radar_precipitation"], "raster_tile")
        self.assertEqual(assignments["dwd"]["official_weather_warnings"], "hazard_feed")
        self.assertEqual(assignments["fmi_lightning"]["lightning_strikes_observed"], "event_feed")
        self.assertEqual(assignments["noaa_goes_glm"]["glm_east_lcfa"], "data_file")
        self.assertEqual(assignments["noaa_swpc"]["solar_suvi_171"], "image_sequence")
        self.assertEqual(assignments["nasa_iss"]["iss_earth_live"], "live_stream")
        self.assertEqual(assignments["nasa_moon"]["moon_lro_wac_global"], "planetary_tile")

    def test_runtime_validator_rejects_static_runtime_drift(self) -> None:
        source = CONSUMER_API_PATH.read_text(encoding="utf-8")
        for marker in (
            "_RESOURCE_TYPES = frozenset",
            "capability_resource_types",
            "consumer capability resource type drift",
            "consumer public capability resource type drift",
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
