"""Static contract test for the P2-SNOW-20 semantic classification."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p2_snow_semantics.v1.json"


class P2SnowSemanticsContractTest(unittest.TestCase):
    """Keep P2-SNOW-20 semantic boundaries stable until intent design."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
        cls.candidates = cls.payload["candidate_classification"]

    def test_direct_snowfall_class_has_exactly_one_candidate(self) -> None:
        items = [
            item for item in self.candidates
            if item["semantic_class"] == "snowfall_amount_recent_interval_forecast_point"
        ]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["provider"], "open_meteo")
        self.assertEqual(items[0]["capability"], "snowfall")
        self.assertEqual(items[0]["quantity"], "snowfall_amount")
        self.assertEqual(items[0]["unit"], "cm")
        self.assertEqual(items[0]["observation_kind"], "forecast")

    def test_snowfall_is_interval_accumulation_not_snow_depth(self) -> None:
        decision = self.payload["direct_snowfall_semantic_decision"]
        self.assertEqual(
            decision["point_value_meaning"],
            "snowfall amount accumulated over the provider runtime interval",
        )
        self.assertIn("snow depth on ground", decision["not_equivalent_to"])
        family = self.payload["semantic_families"][
            "snowfall_amount_recent_interval_forecast_point"
        ]
        self.assertEqual(
            family["accumulation_semantics"],
            "preceding_runtime_interval_sum",
        )

    def test_weather_codes_and_summaries_are_not_snowfall_amount(self) -> None:
        incompatible = {
            item["compatibility"]
            for item in self.candidates
            if item["semantic_class"] in {
                "weather_condition_code_forecast",
                "weather_condition_summary_forecast",
            }
        }
        self.assertNotIn("direct_snowfall_amount", incompatible)

    def test_warning_events_are_not_point_snowfall(self) -> None:
        items = [
            item for item in self.candidates
            if item["semantic_class"] == "official_weather_warning_event"
        ]
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["resource_type"] == "hazard_feed" for item in items))
        self.assertTrue(all(item["observation_kind"] == "warning_event" for item in items))

    def test_snow_leopard_is_explicitly_excluded(self) -> None:
        item = next(
            item for item in self.candidates
            if item["provider"] == "gbif_biodiversity"
            and item["capability"] == "occurrence_density_snow_leopard"
        )
        self.assertEqual(item["semantic_class"], "biodiversity_false_positive")
        self.assertEqual(
            item["compatibility"],
            "exclude_from_meteorological_snow_ice",
        )
        self.assertTrue(
            self.payload["rules"]["snow_leopard_is_not_meteorological_snow_ice"]
        )

    def test_no_fake_multi_provider_interchangeability(self) -> None:
        decision = self.payload["direct_snowfall_semantic_decision"]
        self.assertFalse(decision["multi_provider_interchangeability_proven"])
        self.assertFalse(decision["new_shared_intent_required_from_current_inventory"])
        self.assertEqual(decision["direct_candidates"], ["open_meteo/snowfall"])

    def test_no_provider_priority_or_scoring_decision_is_encoded(self) -> None:
        raw = SEMANTICS_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("provider_priority", raw)
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("routing_score", raw)


if __name__ == "__main__":
    unittest.main()
