"""Static contract test for the P2-WIND-20 semantic classification."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p2_wind_semantics.v1.json"


class P2WindSemanticsContractTest(unittest.TestCase):
    """Keep the P2-WIND-20 boundaries stable until intent design changes them explicitly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
        cls.candidates = cls.payload["candidate_classification"]

    def test_inventory_count_is_preserved(self) -> None:
        self.assertEqual(len(self.candidates), 20)
        self.assertEqual(
            len({(item["provider"], item["capability"]) for item in self.candidates}),
            20,
        )

    def test_speed_gust_direction_are_distinct_semantic_classes(self) -> None:
        families = self.payload["semantic_families"]
        self.assertEqual(
            families["wind_speed_point"]["semantic_quantity"],
            "wind_speed",
        )
        self.assertEqual(
            families["wind_gust_point"]["semantic_quantity"],
            "wind_gust_speed",
        )
        self.assertEqual(
            families["wind_direction_point"]["semantic_quantity"],
            "wind_from_direction",
        )

    def test_raster_text_and_hazard_semantics_stay_separate(self) -> None:
        families = self.payload["semantic_families"]
        self.assertEqual(families["wind_layer"]["resource_type"], "raster_tile")
        self.assertFalse(families["wind_summary_text"]["numeric"])
        self.assertEqual(
            families["wind_hazard_products"]["resource_type"],
            "hazard_feed",
        )

    def test_eccc_direction_is_not_generic_forecast_direction(self) -> None:
        item = next(
            item
            for item in self.candidates
            if item["provider"] == "eccc_geomet"
            and item["capability"] == "wind_direction"
        )
        self.assertEqual(item["observation_kind"], "observation")
        self.assertEqual(
            item["compatibility"],
            "not_generic_direction_without_statistic_contract",
        )

    def test_nowcast_remains_distinct_observation_class(self) -> None:
        nowcasts = [
            item for item in self.candidates
            if item["provider"] == "met_norway"
            and item["capability"].startswith("nowcast_wind_")
        ]
        self.assertEqual(len(nowcasts), 3)
        self.assertTrue(all(item["observation_kind"] == "nowcast" for item in nowcasts))
        self.assertTrue(
            all(
                item["compatibility"]
                == "same_physical_quantity_distinct_observation_class"
                for item in nowcasts
            )
        )

    def test_no_provider_priority_or_scoring_decision_is_encoded(self) -> None:
        raw = SEMANTICS_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("provider_priority", raw)
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("routing_score", raw)


if __name__ == "__main__":
    unittest.main()
