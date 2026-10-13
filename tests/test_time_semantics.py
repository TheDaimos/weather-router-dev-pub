"""Static contract tests for catalog-wide time semantics."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
CAPABILITIES_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "capabilities.response.schema.json"
RESOLVE_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resolve.response.schema.json"
POLICY_PATH = ROOT / "custom_components" / "weather_router" / "consumer_routing_policy.py"
API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"

FIELD_STATES = {"optional_runtime", "not_applicable", "derived_from_data_time_and_runtime_interval"}
FRESHNESS_POLICIES = {"consumer_max_age_optional", "not_applicable"}
ACCUMULATION_STATES = {"not_applicable", "provider_runtime_interval"}


class TimeSemanticsContractTest(unittest.TestCase):
    """P1-070 distinguishes time roles without inventing provider timestamps."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_runtime_and_contract_maps_match(self) -> None:
        self.assertEqual(self.payload, self.contract)

    def test_every_internal_capability_has_time_semantics(self) -> None:
        providers = self.payload["providers"]
        contract = self.payload["capability_time_semantics"]
        assignments = contract["providers"]

        self.assertEqual(
            contract["schema"],
            "weather_router.consumer.capability_time_semantics.v1",
        )
        self.assertEqual(set(contract["field_states"]), FIELD_STATES)
        self.assertEqual(set(contract["freshness_policies"]), FRESHNESS_POLICIES)
        self.assertEqual(set(contract["request_time_modes"]), {"latest"})
        self.assertEqual(set(assignments), set(providers))

        count = 0
        for provider_id, capabilities in providers.items():
            self.assertEqual(set(assignments[provider_id]), set(capabilities), provider_id)
            for capability_id in capabilities:
                item = assignments[provider_id][capability_id]
                self.assertEqual(item["request_time_mode"], "latest")
                for field in (
                    "data_time",
                    "valid_time",
                    "forecast_reference_time",
                    "interval_start",
                    "interval_end",
                    "frame_cadence",
                ):
                    self.assertIn(item[field], FIELD_STATES, f"{provider_id}/{capability_id}")
                accumulation = item["accumulation_period"]
                self.assertTrue(
                    accumulation in ACCUMULATION_STATES
                    or (isinstance(accumulation, str) and accumulation.startswith("P")),
                    f"{provider_id}/{capability_id}",
                )
                self.assertIn(item["freshness_policy"], FRESHNESS_POLICIES)
                count += 1

        self.assertEqual(count, 280)

    def test_one_hour_accumulation_is_explicit_not_inferred_from_display_text(self) -> None:
        time = self.payload["capability_time_semantics"]["providers"]
        self.assertEqual(
            time["dwd"]["icon_eu_precipitation_1h"]["accumulation_period"],
            "PT1H",
        )
        self.assertEqual(
            time["eccc_geomet"]["precipitation_1h"]["accumulation_period"],
            "PT1H",
        )

    def test_reference_imagery_does_not_claim_freshness(self) -> None:
        time = self.payload["capability_time_semantics"]["providers"]
        moon = time["nasa_moon"]["moon_lro_wac_global"]
        self.assertEqual(moon["data_time"], "not_applicable")
        self.assertEqual(moon["freshness_policy"], "not_applicable")

    def test_predictive_and_event_time_axes_are_distinguishable(self) -> None:
        time = self.payload["capability_time_semantics"]["providers"]
        forecast = time["open_meteo"]["temperature"]
        warning = time["bbk_mowas"]["civil_protection_warnings_germany"]
        observation = time["eccc_geomet"]["temperature"]

        self.assertEqual(forecast["forecast_reference_time"], "optional_runtime")
        self.assertEqual(forecast["valid_time"], "optional_runtime")
        self.assertEqual(warning["interval_start"], "optional_runtime")
        self.assertEqual(warning["interval_end"], "optional_runtime")
        self.assertEqual(observation["forecast_reference_time"], "not_applicable")

    def test_public_and_resolve_schemas_expose_time_semantics(self) -> None:
        capabilities = json.loads(CAPABILITIES_SCHEMA_PATH.read_text(encoding="utf-8"))
        resolve = json.loads(RESOLVE_SCHEMA_PATH.read_text(encoding="utf-8"))

        capability_props = capabilities["properties"]["capabilities"]["items"]["properties"]
        self.assertIn("time_semantics", capability_props)

        semantics_props = (
            resolve["properties"]["resource"]["properties"]["semantics"]["properties"]
        )
        self.assertIn("time_semantics", semantics_props)

    def test_runtime_attaches_and_aggregates_static_time_contract(self) -> None:
        policy = POLICY_PATH.read_text(encoding="utf-8")
        api = API_PATH.read_text(encoding="utf-8")
        self.assertIn('time_all = mapping.get("capability_time_semantics", {})', policy)
        self.assertIn('"time_semantics": dict(time_semantics)', policy)
        self.assertIn("def _candidate_time_semantics(", api)
        self.assertIn("def _public_time_semantics(", api)
        self.assertIn('row["time_semantics"] = time_semantics', api)


if __name__ == "__main__":
    unittest.main()
