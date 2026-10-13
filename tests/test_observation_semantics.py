"""Static contract tests for catalog-wide observation kinds."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
POLICY_PATH = ROOT / "custom_components" / "weather_router" / "consumer_routing_policy.py"
API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"

EXPECTED_KINDS = {
    "observation",
    "estimate",
    "observation_forecast",
    "nowcast",
    "forecast",
    "model",
    "warning_event",
    "reference",
}


class ObservationSemanticsContractTest(unittest.TestCase):
    """P1-060 freezes observation/time class independently from source origin."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_runtime_and_contract_maps_match(self) -> None:
        self.assertEqual(self.payload, self.contract)

    def test_every_internal_capability_has_observation_kind(self) -> None:
        providers = self.payload["providers"]
        contract = self.payload["capability_observation_semantics"]
        assignments = contract["providers"]
        self.assertEqual(
            contract["schema"],
            "weather_router.consumer.capability_observation_semantics.v1",
        )
        self.assertEqual(set(contract["allowed_observation_kinds"]), EXPECTED_KINDS)
        self.assertEqual(set(assignments), set(providers))

        count = 0
        for provider_id, capabilities in providers.items():
            self.assertEqual(set(assignments[provider_id]), set(capabilities), provider_id)
            for capability_id in capabilities:
                kind = assignments[provider_id][capability_id]["observation_kind"]
                self.assertIn(kind, EXPECTED_KINDS, f"{provider_id}/{capability_id}")
                self.assertNotEqual(kind, "unspecified")
                count += 1
        self.assertEqual(count, 280)

    def test_existing_pilot_observation_kinds_are_preserved(self) -> None:
        assignments = self.payload["capability_observation_semantics"]["providers"]
        for key, explicit in self.payload.get("candidate_semantics", {}).items():
            provider_id, capability_id = key.split("/", 1)
            self.assertEqual(
                assignments[provider_id][capability_id]["observation_kind"],
                explicit["observation_kind"],
                key,
            )

    def test_reference_observation_kinds(self) -> None:
        a = self.payload["capability_observation_semantics"]["providers"]
        self.assertEqual(a["dwd"]["radar_precipitation"]["observation_kind"], "observation_forecast")
        self.assertEqual(a["dwd"]["radar_precipitation_quality_checked"]["observation_kind"], "observation")
        self.assertEqual(a["nasa_gibs"]["satellite_precipitation_imerg_30min"]["observation_kind"], "estimate")
        self.assertEqual(a["met_norway"]["nowcast_precipitation_rate"]["observation_kind"], "nowcast")
        self.assertEqual(a["open_meteo"]["temperature"]["observation_kind"], "forecast")
        self.assertEqual(a["glofas"]["flood_probability_5y"]["observation_kind"], "model")
        self.assertEqual(a["bbk_mowas"]["civil_protection_warnings_germany"]["observation_kind"], "warning_event")
        self.assertEqual(a["nasa_moon"]["moon_lro_wac_global"]["observation_kind"], "reference")

    def test_runtime_uses_static_observation_contract(self) -> None:
        policy = POLICY_PATH.read_text(encoding="utf-8")
        api = API_PATH.read_text(encoding="utf-8")
        self.assertIn('observation_all = mapping.get("capability_observation_semantics", {})', policy)
        self.assertIn('observation_semantics.get("observation_kind")', policy)
        self.assertIn("candidate observation_kind drift", api)


if __name__ == "__main__":
    unittest.main()
