"""Static contract test for the P2-CLOUD-20 semantic classification."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p2_cloud_semantics.v1.json"


class P2CloudSemanticsContractTest(unittest.TestCase):
    """Keep P2-CLOUD-20 boundaries stable until intent design changes them explicitly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
        cls.candidates = cls.payload["candidate_classification"]

    def test_inventory_count_is_preserved(self) -> None:
        self.assertEqual(len(self.candidates), 28)
        self.assertEqual(
            len({(item["provider"], item["capability"]) for item in self.candidates}),
            28,
        )

    def test_vertical_cloud_layers_are_distinct_semantic_quantities(self) -> None:
        families = self.payload["semantic_families"]
        self.assertEqual(
            families["cloud_cover_total_forecast_point"]["semantic_quantity"],
            "cloud_cover_fraction_total",
        )
        self.assertEqual(
            families["cloud_cover_low_forecast_point"]["semantic_quantity"],
            "cloud_cover_fraction_low",
        )
        self.assertEqual(
            families["cloud_cover_mid_forecast_point"]["semantic_quantity"],
            "cloud_cover_fraction_mid",
        )
        self.assertEqual(
            families["cloud_cover_high_forecast_point"]["semantic_quantity"],
            "cloud_cover_fraction_high",
        )

    def test_eccc_station_observation_is_not_generic_forecast(self) -> None:
        item = next(
            item
            for item in self.candidates
            if item["provider"] == "eccc_geomet"
            and item["capability"] == "cloud_cover"
        )
        self.assertEqual(item["observation_kind"], "observation")
        self.assertEqual(
            item["compatibility"],
            "separate_observation_unknown_static_unit",
        )
        self.assertIsNone(item["unit"])

    def test_model_forecast_cloud_cover_uses_percent(self) -> None:
        forecast_total = [
            item
            for item in self.candidates
            if item["semantic_class"] == "cloud_cover_total_forecast_point"
        ]
        self.assertEqual(len(forecast_total), 4)
        self.assertTrue(all(item["observation_kind"] == "forecast" for item in forecast_total))
        self.assertTrue(all(item["unit"] == "%" for item in forecast_total))

    def test_numeric_values_and_satellite_layers_stay_separate(self) -> None:
        families = self.payload["semantic_families"]
        self.assertEqual(
            families["cloud_cover_total_forecast_point"]["resource_type"],
            "value",
        )
        self.assertEqual(
            families["satellite_cloud_composite_layer"]["resource_type"],
            "raster_tile",
        )
        self.assertFalse(families["satellite_cloud_composite_layer"]["numeric"])

    def test_satellite_product_classes_remain_distinct(self) -> None:
        families = self.payload["semantic_families"]
        names = {
            "satellite_true_color_layer",
            "satellite_geocolor_layer",
            "satellite_clean_infrared_layer",
            "satellite_visible_red_layer",
            "satellite_air_mass_layer",
        }
        self.assertTrue(names.issubset(families))
        self.assertTrue(families["satellite_visible_red_layer"]["daylight_dependency"])
        self.assertFalse(families["satellite_clean_infrared_layer"]["daylight_dependency"])
        self.assertFalse(families["satellite_air_mass_layer"]["daylight_dependency"])

    def test_no_provider_priority_or_scoring_decision_is_encoded(self) -> None:
        raw = SEMANTICS_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("provider_priority", raw)
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("routing_score", raw)


if __name__ == "__main__":
    unittest.main()
