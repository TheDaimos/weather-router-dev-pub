"""Static contract test for the P5-SPACE-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p5_space_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
SWPC_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_swpc.py"


class P5SpaceIntentDesignContractTest(unittest.TestCase):
    """Lock P5-SPACE-30 before runtime implementation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.swpc = SWPC_PATH.read_text(encoding="utf-8")

    def test_design_adds_exactly_one_provider_neutral_public_intent(self) -> None:
        intents = self.design["new_public_intents"]
        self.assertEqual(set(intents), {"space.aurora.probability.grid"})
        self.assertEqual(self.design["public_capability_count_before"], 226)
        self.assertEqual(self.design["public_capability_count_after"], 227)
        self.assertNotIn("noaa", next(iter(intents)))
        self.assertNotIn("swpc", next(iter(intents)))
        self.assertNotIn("ovation", next(iter(intents)))

    def test_aurora_grid_is_single_data_file_candidate(self) -> None:
        contract = self.design["new_public_intents"]["space.aurora.probability.grid"]
        self.assertEqual(contract["resource_types"], ["data_file"])
        self.assertEqual(
            contract["candidates"],
            ["noaa_swpc/aurora_ovation_latest"],
        )
        self.assertFalse(contract["intent_contract"]["provider_priority"])
        self.assertFalse(contract["intent_contract"]["cross_provider_dedup"])

    def test_ovation_semantics_are_forecast_and_global_earth_grid(self) -> None:
        candidate = self.design["candidate_semantics"][
            "noaa_swpc/aurora_ovation_latest"
        ]
        self.assertEqual(candidate["source"]["data_origin"], "space_weather_model")
        self.assertEqual(
            candidate["source"]["measurement_method"], "aurora_ovation_model"
        )
        self.assertEqual(candidate["observation"]["observation_kind"], "forecast")
        self.assertEqual(candidate["resource"]["type"], "data_file")
        self.assertEqual(candidate["resource"]["format"], "json")
        self.assertEqual(candidate["allowed_contexts"], ["global"])
        coverage = candidate["coverage"]
        self.assertEqual(coverage["coverage_scope"], "global")
        self.assertEqual(coverage["coverage_evidence"], "machine_readable_runtime")
        self.assertEqual(coverage["routing_authority"], "advisory")
        self.assertEqual(coverage["coordinate_space"], "earth")
        self.assertFalse(coverage["endpoint_reachability_is_coverage"])

    def test_time_contract_keeps_observation_and_forecast_time_separate(self) -> None:
        time = self.design["candidate_semantics"][
            "noaa_swpc/aurora_ovation_latest"
        ]["time"]
        self.assertEqual(time["data_time"], "optional_runtime")
        self.assertEqual(time["valid_time"], "optional_runtime")
        self.assertEqual(time["source_observation_time_field"], "Observation Time")
        self.assertEqual(time["source_forecast_time_field"], "Forecast Time")

    def test_astronomy_hardening_preserves_point_requirement(self) -> None:
        hardening = self.design["astronomy_coverage_hardening"]
        self.assertEqual(hardening["candidate_count"], 24)
        self.assertEqual(hardening["to"]["coverage_scope"], "global")
        self.assertEqual(
            hardening["to"]["coverage_evidence"], "static_provider_contract"
        )
        self.assertEqual(hardening["to"]["routing_authority"], "advisory")
        self.assertEqual(hardening["required_context"], "point")
        self.assertFalse(hardening["global_request_without_coordinates"])

    def test_design_declares_additive_phase_40_implementation(self) -> None:
        self.assertEqual(self.design["implementation_phase"], "P5-SPACE-40")
        self.assertEqual(self.design["consumer_migration_phase"], "P7-020")
        self.assertEqual(
            self.design["new_public_intents"]["space.aurora.probability.grid"]["candidates"],
            ["noaa_swpc/aurora_ovation_latest"],
        )

    def test_scope_does_not_smuggle_in_kp_or_visibility_fusion(self) -> None:
        excluded = set(self.design["explicitly_not_added"])
        self.assertIn("Kp public capability", excluded)
        self.assertIn("local aurora visibility probability", excluded)
        self.assertIn("cloud or darkness fusion", excluded)
        self.assertIn("provider priority", excluded)


if __name__ == "__main__":
    unittest.main()
