"""Static contract test for the P2-TEMP-20 semantic classification."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p2_temperature_semantics.v1.json"


class P2TemperatureSemanticsContractTest(unittest.TestCase):
    """Keep P2-TEMP-20 boundaries stable until intent design changes them explicitly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
        cls.candidates = cls.payload["candidate_classification"]

    def test_inventory_count_is_preserved(self) -> None:
        self.assertEqual(len(self.candidates), 11)
        self.assertEqual(
            len({(item["provider"], item["capability"]) for item in self.candidates}),
            11,
        )

    def test_forecast_temperature_class_contains_six_candidates(self) -> None:
        items = [
            item
            for item in self.candidates
            if item["semantic_class"] == "air_temperature_forecast_point"
        ]
        self.assertEqual(len(items), 6)
        self.assertTrue(all(item["resource_type"] == "value" for item in items))
        self.assertTrue(all(item["observation_kind"] == "forecast" for item in items))
        self.assertTrue(all(item["unit"] == "°C" for item in items))

    def test_eccc_station_observation_is_separate(self) -> None:
        item = next(
            item
            for item in self.candidates
            if item["provider"] == "eccc_geomet"
            and item["capability"] == "temperature"
        )
        self.assertEqual(item["semantic_class"], "air_temperature_station_observation")
        self.assertEqual(item["observation_kind"], "observation")
        self.assertEqual(item["compatibility"], "separate_observation")

    def test_nowcast_is_separate_from_forecast(self) -> None:
        item = next(
            item
            for item in self.candidates
            if item["provider"] == "met_norway"
            and item["capability"] == "nowcast_temperature"
        )
        self.assertEqual(item["semantic_class"], "air_temperature_nowcast_point")
        self.assertEqual(item["observation_kind"], "nowcast")

    def test_dwd_temperature_is_raster_model_field(self) -> None:
        item = next(
            item
            for item in self.candidates
            if item["provider"] == "dwd"
            and item["capability"] == "icon_temperature_2m"
        )
        self.assertEqual(item["resource_type"], "raster_tile")
        self.assertEqual(item["semantic_class"], "air_temperature_2m_model_layer")

    def test_fire_temperature_is_not_numeric_air_temperature(self) -> None:
        family = self.payload["semantic_families"]["fire_temperature_satellite_layer"]
        self.assertFalse(family["numeric"])
        self.assertIsNone(family["semantic_quantity"])
        self.assertEqual(family["resource_type"], "raster_tile")

    def test_no_provider_priority_or_scoring_decision_is_encoded(self) -> None:
        raw = SEMANTICS_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("provider_priority", raw)
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("routing_score", raw)


if __name__ == "__main__":
    unittest.main()
