"""Static contract test for the P2-UV-20 semantic classification."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p2_uv_semantics.v1.json"


class P2UvSemanticsContractTest(unittest.TestCase):
    """Keep P2-UV-20 boundaries stable until intent design changes them explicitly."""

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

    def test_clear_sky_forecast_class_contains_two_candidates(self) -> None:
        items = [
            item for item in self.candidates
            if item["semantic_class"] == "uv_index_clear_sky_forecast_point"
        ]
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["resource_type"] == "value" for item in items))
        self.assertTrue(all(item["observation_kind"] == "forecast" for item in items))
        self.assertTrue(all(item["sky_condition"] == "clear_sky" for item in items))
        self.assertTrue(
            all(item["canonical_unit_for_future_routing"] == "1" for item in items)
        )
        self.assertEqual(
            {(item["provider"], item["capability"]) for item in items},
            {("open_meteo", "uv_index_clear_sky"), ("met_norway", "uv_index")},
        )

    def test_all_sky_current_is_separate(self) -> None:
        item = next(
            item for item in self.candidates
            if item["provider"] == "open_meteo"
            and item["capability"] == "uv_index"
        )
        self.assertEqual(item["semantic_class"], "uv_index_all_sky_forecast_point")
        self.assertEqual(item["compatibility"], "separate_all_sky_current")

    def test_daily_maxima_are_separate_from_current_values(self) -> None:
        daily = [
            item for item in self.candidates
            if item["temporal_meaning"] == "maximum_for_local_day_today"
        ]
        self.assertEqual(len(daily), 2)
        self.assertTrue(
            all(item["compatibility"].startswith("separate_") for item in daily)
        )

    def test_uv_unit_is_dimensionless_one(self) -> None:
        self.assertTrue(self.payload["rules"]["uv_index_is_dimensionless"])
        self.assertTrue(self.payload["rules"]["canonical_uv_unit_is_one"])
        self.assertTrue(
            all(item["canonical_unit_for_future_routing"] == "1" for item in self.candidates)
        )

    def test_semantic_rules_keep_sky_and_time_classes_separate(self) -> None:
        rules = self.payload["rules"]
        self.assertTrue(rules["clear_sky_is_not_all_sky"])
        self.assertTrue(rules["daily_maximum_is_not_current_value"])
        self.assertTrue(rules["solar_euv_imagery_is_not_terrestrial_uv_index"])
        self.assertTrue(rules["unknown_coverage_stays_unknown"])

    def test_no_provider_priority_or_scoring_decision_is_encoded(self) -> None:
        raw = SEMANTICS_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("provider_priority", raw)
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("routing_score", raw)


if __name__ == "__main__":
    unittest.main()
