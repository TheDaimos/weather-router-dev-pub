"""Static contract test for the P3-THUNDER-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p3_thunder_intent_design.v1.json"


class P3ThunderIntentDesignTest(unittest.TestCase):
    """Protect P3-THUNDER-30 intent decisions before runtime implementation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.intents = cls.payload["intents"]

    def test_no_new_public_capability_and_counts_stay_one_two(self) -> None:
        decisions = self.payload["decisions"]
        self.assertEqual(decisions["new_public_capabilities"], [])
        self.assertEqual(decisions["total_public_capabilities_after_design"], 226)
        self.assertEqual(
            decisions["standard_core_candidate_counts"],
            {
                "weather.convection.thunderstorm_cells": 1,
                "weather.point.thunder_probability": 2,
            },
        )

    def test_cell_intent_remains_single_dwd_raster_nowcast(self) -> None:
        intent = self.intents["weather.convection.thunderstorm_cells"]
        self.assertEqual(intent["candidates"], ["dwd/thunderstorm_cells"])
        self.assertEqual(intent["resource_type"], "raster_tile")
        self.assertEqual(intent["observation_kind_policy"], "nowcast")
        self.assertEqual(intent["coverage"], "candidate_hard_bbox")
        self.assertFalse(intent["numeric_interchangeable"])

    def test_probability_intent_is_exactly_next_one_hour_percent(self) -> None:
        intent = self.intents["weather.point.thunder_probability"]
        self.assertEqual(
            intent["candidates"],
            [
                "met_norway/thunder_probability",
                "smhi/thunder_probability",
            ],
        )
        self.assertEqual(intent["resource_type"], "value")
        self.assertEqual(intent["canonical_unit"], "%")
        self.assertEqual(intent["numeric_range_inclusive"], [0, 100])
        self.assertEqual(intent["required_interval_seconds"], 3600)
        self.assertEqual(
            intent["temporal_policy"],
            "next_1_hour_thunder_probability",
        )
        self.assertTrue(intent["numeric_interchangeable"])

    def test_probability_candidates_must_prove_one_hour_interval(self) -> None:
        req = self.payload["candidate_requirements"]
        self.assertEqual(
            req["met_norway/thunder_probability"]["required_period_marker"],
            "1h",
        )
        self.assertEqual(
            req["smhi/thunder_probability"]["required_interval_seconds"],
            3600,
        )
        self.assertEqual(
            req["smhi/thunder_probability"]["missing_interval"],
            "fail_closed",
        )

    def test_forbidden_fallbacks_keep_thunder_classes_separate(self) -> None:
        forbidden = set(self.payload["forbidden_fallbacks"])
        for item in {
            "thunderstorm_cell_to_thunder_probability",
            "thunder_probability_to_thunderstorm_cell",
            "thunder_probability_to_official_warning",
            "lightning_observation_to_thunder_probability",
            "met_norway_6h_or_12h_probability_to_next_1h_probability",
        }:
            self.assertIn(item, forbidden)

    def test_invariants_preserve_provider_neutral_routing(self) -> None:
        invariants = self.payload["invariants"]
        self.assertTrue(invariants["provider_id_is_not_scoring_axis"])
        self.assertTrue(invariants["profiles_remain_deny_only"])
        self.assertTrue(invariants["unknown_coverage_stays_unknown_preflight"])
        self.assertTrue(invariants["endpoint_reachability_is_not_coverage"])
        self.assertTrue(invariants["no_provider_specific_consumer_logic"])
        self.assertTrue(invariants["private_extensions_outside_standard_core_contract"])

    def test_no_provider_priority_or_score_is_encoded(self) -> None:
        raw = DESIGN_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("provider_priority", raw)
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("routing_score", raw)


if __name__ == "__main__":
    unittest.main()
