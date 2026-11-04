"""Independent static acceptance for P5-SPACE-50."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
DRAFT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
DESIGN_PATH = ROOT / "docs" / "p5_space_intent_design.v1.json"
SWPC_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_swpc.py"
CONSUMER_API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"
LAB_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab.js"
LOADER_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab-dev-loader.js"


class P5SpaceStaticAcceptanceTest(unittest.TestCase):
    """Accept P5-SPACE independently from the implementation regression."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.swpc = SWPC_PATH.read_text(encoding="utf-8")
        cls.consumer_api = CONSUMER_API_PATH.read_text(encoding="utf-8")
        cls.const = CONST_PATH.read_text(encoding="utf-8")
        cls.lab = LAB_PATH.read_text(encoding="utf-8")
        cls.loader = LOADER_PATH.read_text(encoding="utf-8")

    def _candidates_for(self, public_id: str) -> list[str]:
        result: list[str] = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    result.append(f"{provider_id}/{capability_id}")
        return result

    def test_01_catalog_is_227_and_existing_space_contracts_are_preserved(self) -> None:
        self.assertEqual(len(self.mapping["public_capabilities"]), 227)
        space_ids = {
            item for item in self.mapping["public_capabilities"]
            if item.startswith("space.")
        }
        self.assertEqual(len(space_ids), 33)
        self.assertIn("space.aurora.probability.grid", space_ids)
        self.assertEqual(self.design["preserve_existing_space_public_capabilities"], 32)

    def test_02_public_aurora_intent_is_provider_neutral(self) -> None:
        public_id = "space.aurora.probability.grid"
        self.assertNotIn("noaa", public_id)
        self.assertNotIn("swpc", public_id)
        self.assertNotIn("ovation", public_id)
        contract = self.mapping["public_capabilities"][public_id]
        self.assertEqual(contract["family"], "aurora")
        self.assertEqual(contract["phenomena"], ["aurora"])
        self.assertEqual(contract["strategy"], "single")
        self.assertEqual(contract["resource_types"], ["data_file"])

    def test_03_exactly_one_ovation_candidate_exists(self) -> None:
        self.assertEqual(
            self._candidates_for("space.aurora.probability.grid"),
            ["noaa_swpc/aurora_ovation_latest"],
        )

    def test_04_ovation_resource_contract_is_machine_readable_json(self) -> None:
        self.assertEqual(
            self.mapping["capability_resource_types"]["providers"]["noaa_swpc"][
                "aurora_ovation_latest"
            ],
            "data_file",
        )
        self.assertIn("async def async_get_data_file(", self.swpc)
        self.assertIn("/json/ovation_aurora_latest.json", self.swpc)
        self.assertIn('"format": "json"', self.swpc)
        self.assertIn('"transport": "direct"', self.swpc)
        for required in ('"Observation Time"', '"Forecast Time"', '"Data Format"', '"coordinates"'):
            self.assertIn(required, self.swpc)

    def test_05_ovation_is_model_forecast_not_direct_observation(self) -> None:
        source = self.mapping["capability_source_semantics"]["providers"]["noaa_swpc"][
            "aurora_ovation_latest"
        ]
        observation = self.mapping["capability_observation_semantics"]["providers"][
            "noaa_swpc"
        ]["aurora_ovation_latest"]
        self.assertEqual(source["data_origin"], "space_weather_model")
        self.assertEqual(source["measurement_method"], "aurora_ovation_model")
        self.assertEqual(observation["observation_kind"], "forecast")
        self.assertIn('"source_class": "forecast"', self.swpc)

    def test_06_observation_and_forecast_time_remain_separate(self) -> None:
        time = self.mapping["capability_time_semantics"]["providers"]["noaa_swpc"][
            "aurora_ovation_latest"
        ]
        self.assertEqual(time["data_time"], "optional_runtime")
        self.assertEqual(time["valid_time"], "optional_runtime")
        self.assertEqual(time["forecast_reference_time"], "optional_runtime")
        self.assertIn('"data_time": observation_time', self.swpc)
        self.assertIn('"valid_time": forecast_time', self.swpc)
        self.assertIn('valid_time = _provider_time(candidate, "valid_time"', self.consumer_api)

    def test_07_aurora_coverage_is_global_runtime_advisory_earth(self) -> None:
        coverage = self.mapping["capability_coverage_semantics"]["providers"]["noaa_swpc"][
            "aurora_ovation_latest"
        ]
        self.assertEqual(coverage["coverage_scope"], "global")
        self.assertEqual(coverage["coverage_evidence"], "machine_readable_runtime")
        self.assertEqual(coverage["routing_authority"], "advisory")
        self.assertEqual(coverage["coordinate_space"], "earth")
        self.assertFalse(coverage["endpoint_reachability_is_coverage"])
        self.assertNotIn("async def async_get_coverage(", self.swpc)

    def test_08_grid_contract_does_not_claim_local_visibility(self) -> None:
        self.assertIn('"local_visibility_guarantee": False', self.swpc)
        invariants = set(self.design["invariants"])
        self.assertIn("Grid context is not Point or Nearby semantics.", invariants)
        excluded = set(self.design["explicitly_not_added"])
        self.assertIn("local aurora visibility probability", excluded)

    def test_09_astronomy_has_24_global_coverage_point_candidates(self) -> None:
        provider = "met_norway_astronomy"
        capabilities = self.mapping["providers"][provider]
        coverage = self.mapping["capability_coverage_semantics"]["providers"][provider]
        self.assertEqual(len(capabilities), 24)
        self.assertEqual(set(capabilities), set(coverage))
        for item in coverage.values():
            self.assertEqual(item["coverage_scope"], "global")
            self.assertEqual(item["coverage_evidence"], "static_provider_contract")
            self.assertEqual(item["routing_authority"], "advisory")
            self.assertEqual(item["coordinate_space"], "earth")
            self.assertFalse(item["endpoint_reachability_is_coverage"])

    def test_10_astronomy_global_coverage_does_not_create_global_resource_contract(self) -> None:
        for public_id, contract in self.mapping["public_capabilities"].items():
            if public_id.startswith("space.moon.") and public_id != "space.moon.tiles":
                self.assertEqual(contract["resource_types"], ["value"])
            if public_id.startswith("space.sun."):
                self.assertEqual(contract["resource_types"], ["value"])
        self.assertFalse(
            self.design["astronomy_coverage_hardening"]["global_request_without_coordinates"]
        )

    def test_11_runtime_and_draft_maps_are_identical(self) -> None:
        self.assertEqual(self.mapping, self.draft)

    def test_12_no_kp_generic_severity_or_cross_resource_fallback_is_added(self) -> None:
        ids = set(self.mapping["public_capabilities"])
        self.assertFalse(any(".kp" in item or item.endswith(".kp") for item in ids))
        self.assertNotIn("space.weather.current", ids)
        self.assertNotIn("space.weather.severity", ids)
        self.assertFalse(self.design["new_public_intents"]["space.aurora.probability.grid"][
            "intent_contract"
        ]["provider_priority"])
        self.assertFalse(self.design["new_public_intents"]["space.aurora.probability.grid"][
            "intent_contract"
        ]["cross_provider_dedup"])

    def test_13_version_surfaces_are_synchronized(self) -> None:
        import re
        def extract(source, name):
            match = re.search(r"\b" + re.escape(name)
                              + r'(?:: Final)?\s*=\s*"([^"]+)"', source)
            self.assertIsNotNone(match, name)
            return match.group(1)
        build = extract(self.const, "DEV_BUILD_VERSION")
        loader_rev = extract(self.const, "DEV_LOADER_REV")
        self.assertEqual(extract(self.lab, "WR_LAB_BUILD_VERSION"), build)
        self.assertEqual(extract(self.loader, "WR_LAB_BUILD_VERSION"), build)
        self.assertEqual(extract(self.loader, "LOADER_REV"), loader_rev)


if __name__ == "__main__":
    unittest.main()
