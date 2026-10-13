"""Static contract test for the P2-UV-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p2_uv_intent_design.v1.json"


class P2UvIntentDesignTest(unittest.TestCase):
    """Keep the four UV intent boundaries stable until implementation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.intents = cls.payload["intents"]

    def test_no_new_public_ids_are_introduced(self) -> None:
        self.assertEqual(self.payload["decisions"]["new_public_capabilities"], [])
        self.assertEqual(
            set(self.intents),
            {
                "weather.point.uv_index",
                "weather.point.uv_index_clear_sky",
                "weather.point.uv_index_max_today",
                "weather.point.uv_index_clear_sky_max_today",
            },
        )

    def test_only_clear_sky_current_is_multi_candidate(self) -> None:
        multi = {
            intent: tuple(spec["candidates"])
            for intent, spec in self.intents.items()
            if len(spec["candidates"]) > 1
        }
        self.assertEqual(
            multi,
            {
                "weather.point.uv_index_clear_sky": (
                    "open_meteo/uv_index_clear_sky",
                    "met_norway/uv_index",
                )
            },
        )

    def test_all_intents_use_dimensionless_unit_one(self) -> None:
        for spec in self.intents.values():
            self.assertEqual(spec["canonical_unit"], "1")
            self.assertEqual(spec["unit_policy"], "dimensionless_one")
            self.assertEqual(spec["quantity_policy"], "uv_index")
            self.assertEqual(spec["observation_kind_policy"], "forecast")

    def test_current_and_daily_maximum_policies_are_distinct(self) -> None:
        self.assertEqual(
            self.intents["weather.point.uv_index"]["temporal_policy"],
            "current_or_near_current_forecast",
        )
        self.assertEqual(
            self.intents["weather.point.uv_index_max_today"]["temporal_policy"],
            "maximum_for_local_day_today",
        )
        self.assertEqual(
            self.intents["weather.point.uv_index_clear_sky_max_today"]["temporal_policy"],
            "maximum_for_local_day_today",
        )

    def test_all_sky_and_clear_sky_policies_are_distinct(self) -> None:
        self.assertEqual(
            self.intents["weather.point.uv_index"]["sky_condition_policy"],
            "all_sky_or_cloud_affected",
        )
        self.assertEqual(
            self.intents["weather.point.uv_index_clear_sky"]["sky_condition_policy"],
            "clear_sky",
        )

    def test_forbidden_fallbacks_include_sky_time_and_suvi_boundaries(self) -> None:
        forbidden = set(self.payload["forbidden_fallbacks"])
        for item in {
            "all_sky_to_clear_sky",
            "clear_sky_to_all_sky",
            "current_to_daily_maximum",
            "daily_maximum_to_current",
            "space.solar.suvi.*",
        }:
            self.assertIn(item, forbidden)

    def test_invariants_keep_routing_provider_neutral(self) -> None:
        invariants = self.payload["invariants"]
        self.assertTrue(invariants["provider_id_is_not_scoring_axis"])
        self.assertTrue(invariants["profiles_remain_deny_only"])
        self.assertTrue(invariants["unknown_coverage_stays_unknown"])
        self.assertTrue(invariants["no_provider_specific_consumer_logic"])


if __name__ == "__main__":
    unittest.main()
