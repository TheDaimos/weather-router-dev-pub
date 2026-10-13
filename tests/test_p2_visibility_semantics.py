"""Static contract test for the P2-VIS-20 semantic classification."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p2_visibility_semantics.v1.json"


class P2VisibilitySemanticsContractTest(unittest.TestCase):
    """Keep P2-VIS-20 boundaries stable until intent design changes them explicitly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
        cls.candidates = cls.payload["candidate_classification"]

    def test_inventory_count_is_preserved(self) -> None:
        self.assertEqual(len(self.candidates), 5)
        self.assertEqual(
            len({(item["provider"], item["capability"]) for item in self.candidates}),
            5,
        )

    def test_visibility_forecast_class_contains_three_candidates(self) -> None:
        items = [
            item for item in self.candidates
            if item["semantic_class"] == "visibility_distance_forecast_point"
        ]
        self.assertEqual(len(items), 3)
        self.assertTrue(all(item["resource_type"] == "value" for item in items))
        self.assertTrue(all(item["observation_kind"] == "forecast" for item in items))
        self.assertTrue(
            all(item["canonical_unit_for_future_routing"] == "m" for item in items)
        )
        self.assertEqual({item["provider_unit"] for item in items}, {"m", "km"})

    def test_eccc_station_observation_is_separate(self) -> None:
        item = next(
            item for item in self.candidates
            if item["provider"] == "eccc_geomet"
            and item["capability"] == "visibility"
        )
        self.assertEqual(
            item["semantic_class"], "visibility_distance_station_observation"
        )
        self.assertEqual(item["observation_kind"], "observation")
        self.assertEqual(item["compatibility"], "separate_observation")

    def test_fog_fraction_is_separate_physical_quantity(self) -> None:
        item = next(
            item for item in self.candidates
            if item["provider"] == "met_norway"
            and item["capability"] == "fog"
        )
        self.assertEqual(item["semantic_class"], "fog_fraction_forecast_point")
        self.assertEqual(item["provider_unit"], "%")
        self.assertEqual(item["compatibility"], "separate_physical_quantity")

    def test_semantic_rules_keep_fog_and_visibility_separate(self) -> None:
        rules = self.payload["rules"]
        self.assertTrue(rules["fog_fraction_is_not_visibility_distance"])
        self.assertTrue(rules["observation_is_not_forecast"])
        self.assertTrue(rules["unknown_coverage_stays_unknown"])

    def test_no_provider_priority_or_scoring_decision_is_encoded(self) -> None:
        raw = SEMANTICS_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("provider_priority", raw)
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("routing_score", raw)


if __name__ == "__main__":
    unittest.main()
