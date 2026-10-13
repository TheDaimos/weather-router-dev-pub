"""Static contract tests for catalog-wide coverage semantics."""

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
REGISTRY_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "registry.json"
PROVIDERS_DIR = ROOT / "custom_components" / "weather_router" / "providers"


class CoverageSemanticsContractTest(unittest.TestCase):
    """P1-080 separates reachability, spatial evidence and routing authority."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_runtime_and_contract_maps_match(self) -> None:
        self.assertEqual(self.payload, self.contract)

    def test_every_internal_capability_has_coverage_semantics(self) -> None:
        providers = self.payload["providers"]
        contract = self.payload["capability_coverage_semantics"]
        assignments = contract["providers"]
        self.assertEqual(
            contract["schema"],
            "weather_router.consumer.capability_coverage_semantics.v1",
        )
        self.assertEqual(set(assignments), set(providers))

        count = 0
        for provider_id, capabilities in providers.items():
            self.assertEqual(set(assignments[provider_id]), set(capabilities), provider_id)
            for capability_id in capabilities:
                item = assignments[provider_id][capability_id]
                self.assertIn(item["coverage_scope"], contract["coverage_scopes"])
                self.assertIn(item["coverage_evidence"], contract["coverage_evidence"])
                self.assertIn(item["routing_authority"], contract["routing_authorities"])
                self.assertIn(item["coordinate_space"], contract["coordinate_spaces"])
                self.assertIs(item["endpoint_reachability_is_coverage"], False)
                count += 1
        self.assertEqual(count, 280)

    def test_hard_coverage_is_machine_readable_only(self) -> None:
        assignments = self.payload["capability_coverage_semantics"]["providers"]
        hard = []
        for provider_id, capabilities in assignments.items():
            for capability_id, item in capabilities.items():
                if item["routing_authority"] == "hard":
                    hard.append((provider_id, capability_id, item))
                    self.assertEqual(
                        item["coverage_evidence"],
                        "machine_readable_runtime",
                    )
                    self.assertEqual(item["coordinate_space"], "earth")
        self.assertEqual(len(hard), 26)

    def test_every_hard_coverage_provider_implements_async_get_coverage(self) -> None:
        assignments = self.payload["capability_coverage_semantics"]["providers"]
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        module_by_provider = {
            (entry.get("id") or entry.get("provider_id") or entry["module"]): entry["module"]
            for entry in registry["providers"]
        }

        hard_providers = {
            provider_id
            for provider_id, capabilities in assignments.items()
            if any(item["routing_authority"] == "hard" for item in capabilities.values())
        }
        self.assertTrue(hard_providers)

        for provider_id in sorted(hard_providers):
            self.assertIn(provider_id, module_by_provider, provider_id)
            source = (PROVIDERS_DIR / f"{module_by_provider[provider_id]}.py").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                "async def async_get_coverage(",
                source,
                f"{provider_id}: hard coverage contract without async_get_coverage()",
            )

    def test_precipitation_reference_coverage_semantics(self) -> None:
        a = self.payload["capability_coverage_semantics"]["providers"]
        self.assertEqual(a["dwd"]["radar_precipitation_quality_checked"]["routing_authority"], "hard")
        self.assertEqual(a["nasa_gibs"]["satellite_precipitation_imerg_30min"]["routing_authority"], "hard")
        self.assertEqual(a["rainviewer"]["radar_reflectivity"]["coverage_scope"], "unknown")
        self.assertEqual(a["rainviewer"]["radar_reflectivity"]["routing_authority"], "none")

    def test_event_geometry_is_context_filter_not_source_coverage(self) -> None:
        a = self.payload["capability_coverage_semantics"]["providers"]
        fmi = a["fmi_lightning"]["lightning_strikes_observed"]
        self.assertEqual(fmi["coverage_scope"], "dynamic")
        self.assertEqual(fmi["coverage_evidence"], "runtime_event_geometry")
        self.assertEqual(fmi["routing_authority"], "context_filter")

    def test_non_earth_coordinate_spaces_are_explicit(self) -> None:
        a = self.payload["capability_coverage_semantics"]["providers"]
        self.assertEqual(a["nasa_moon"]["moon_lro_wac_global"]["coordinate_space"], "moon")
        self.assertEqual(a["noaa_swpc"]["solar_suvi_171"]["coordinate_space"], "sun")
        self.assertEqual(a["nasa_iss"]["iss_earth_live"]["coordinate_space"], "orbital")

    def test_contracts_expose_coverage_semantics(self) -> None:
        capabilities = json.loads(CAPABILITIES_SCHEMA_PATH.read_text(encoding="utf-8"))
        resolve = json.loads(RESOLVE_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertIn(
            "coverage_semantics",
            capabilities["properties"]["capabilities"]["items"]["properties"],
        )
        self.assertIn(
            "coverage_semantics",
            resolve["properties"]["resource"]["properties"]["semantics"]["properties"],
        )

    def test_runtime_never_treats_endpoint_reachability_as_coverage(self) -> None:
        policy = POLICY_PATH.read_text(encoding="utf-8")
        api = API_PATH.read_text(encoding="utf-8")
        self.assertIn('coverage_all = mapping.get("capability_coverage_semantics", {})', policy)
        self.assertIn('"coverage_semantics": dict(coverage_semantics)', policy)
        self.assertIn("endpoint reachability must never be coverage evidence", api)
        self.assertIn("hard coverage contract has no machine coverage provider", api)
        self.assertIn("def _public_coverage_semantics(", api)


if __name__ == "__main__":
    unittest.main()
