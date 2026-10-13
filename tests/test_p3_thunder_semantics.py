"""Static contract test for the P3-THUNDER-20 semantic classification."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p3_thunder_semantics.v1.json"


class P3ThunderSemanticsContractTest(unittest.TestCase):
    """Keep P3-THUNDER-20 boundaries stable until intent design changes them explicitly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
        cls.candidates = cls.payload["candidate_classification"]

    def test_inventory_count_is_preserved(self) -> None:
        self.assertEqual(len(self.candidates), 3)
        self.assertEqual(
            len({(item["provider"], item["capability"]) for item in self.candidates}),
            3,
        )

    def test_cell_nowcast_remains_a_separate_raster_contract(self) -> None:
        item = next(item for item in self.candidates if item["provider"] == "dwd")
        self.assertEqual(
            item["semantic_class"],
            "convective_thunderstorm_cell_nowcast_raster",
        )
        self.assertEqual(item["resource_type"], "raster_tile")
        self.assertEqual(item["observation_kind"], "nowcast")
        self.assertEqual(item["coverage"], "hard_bbox")

    def test_probability_candidates_share_class_but_not_proven_temporal_equivalence(self) -> None:
        items = [
            item for item in self.candidates
            if item["semantic_class"] == "thunderstorm_probability_point_forecast"
        ]
        self.assertEqual(
            {(item["provider"], item["capability"]) for item in items},
            {
                ("met_norway", "thunder_probability"),
                ("smhi", "thunder_probability"),
            },
        )
        self.assertTrue(all(item["quantity"] == "thunderstorm_probability" for item in items))
        self.assertTrue(all(item["unit"] == "%" for item in items))
        self.assertTrue(
            all(
                item["compatibility"]
                == "same_probability_class_temporal_equivalence_not_proven"
                for item in items
            )
        )

    def test_probability_numeric_contract_is_percent_0_to_100(self) -> None:
        rules = self.payload["numeric_rules"]["thunderstorm_probability"]
        self.assertEqual(rules["canonical_unit"], "%")
        self.assertEqual(rules["minimum"], 0)
        self.assertEqual(rules["maximum"], 100)
        self.assertTrue(rules["inclusive"])
        self.assertFalse(rules["boolean_allowed"])
        self.assertTrue(rules["fail_closed_on_invalid_unit_or_range"])

    def test_probability_time_semantics_are_not_silently_equalized(self) -> None:
        met = next(item for item in self.candidates if item["provider"] == "met_norway")
        smhi = next(item for item in self.candidates if item["provider"] == "smhi")
        self.assertNotEqual(
            met["forecast_period_semantics"],
            smhi["forecast_period_semantics"],
        )
        self.assertIn("1h_6h_12h", met["forecast_period_semantics"])
        self.assertIn("not_explicit", smhi["forecast_period_semantics"])

    def test_semantic_rules_preserve_hard_boundaries(self) -> None:
        rules = self.payload["rules"]
        self.assertTrue(rules["cell_is_not_probability"])
        self.assertTrue(rules["probability_is_not_warning"])
        self.assertTrue(rules["probability_is_not_lightning_observation"])
        self.assertTrue(rules["raster_is_not_numeric_point_value"])
        self.assertTrue(rules["same_quantity_and_unit_do_not_prove_temporal_interchangeability"])
        self.assertTrue(rules["missing_probability_is_not_zero"])
        self.assertTrue(rules["unknown_coverage_stays_unknown_preflight"])
        self.assertTrue(rules["private_extensions_outside_standard_core_contract"])

    def test_no_provider_priority_or_scoring_decision_is_encoded(self) -> None:
        raw = SEMANTICS_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("provider_priority", raw)
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("routing_score", raw)


if __name__ == "__main__":
    unittest.main()
