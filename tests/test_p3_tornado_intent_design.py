"""Static contract test for the P3-TORNADO-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p3_tornado_intent_design.v1.json"


class P3TornadoIntentDesignContractTest(unittest.TestCase):
    """Protect the tornado intent design until implementation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))

    def test_no_new_public_capability_is_introduced(self) -> None:
        self.assertEqual(self.payload["public_capability_count_before"], 226)
        self.assertEqual(self.payload["public_capabilities_added"], 0)
        self.assertEqual(self.payload["public_capability_count_after"], 226)
        self.assertEqual(
            self.payload["public_intent"]["id"],
            "weather.warning.official",
        )
        self.assertEqual(self.payload["public_intent"]["action"], "reuse_existing")

    def test_candidate_set_remains_dwd_and_nws(self) -> None:
        self.assertEqual(
            self.payload["public_intent"]["candidates"],
            [
                "dwd/official_weather_warnings",
                "noaa_nws/official_weather_alerts",
            ],
        )

    def test_tornado_and_waterspout_use_hazard_filter(self) -> None:
        self.assertEqual(
            self.payload["public_intent"]["hazard_filter_values"],
            ["tornado", "waterspout"],
        )

    def test_additive_event_fields_are_explicit(self) -> None:
        fields = self.payload["additive_event_fields"]
        self.assertEqual(
            fields["tornado_semantic_class"],
            [
                "official_tornado_alert_event",
                "official_waterspout_alert_event",
            ],
        )
        self.assertEqual(
            fields["alert_stage"],
            ["warning", "watch", "outlook", "statement", "unspecified"],
        )
        self.assertEqual(
            fields["hazard_match_scope"],
            ["explicit_event", "contextual_text"],
        )

    def test_filter_extensions_are_provider_neutral(self) -> None:
        self.assertEqual(
            self.payload["event_filter_extensions"],
            [
                "alert_stages",
                "hazard_match_scopes",
                "tornado_semantic_classes",
            ],
        )

    def test_no_confirmed_tornado_promotion_is_designed(self) -> None:
        excluded = set(self.payload["explicitly_not_implemented"])
        self.assertIn("confirmed_tornado_observation_event", excluded)
        self.assertIn("radar_rotation_signature", excluded)
        self.assertIn("tornado_probability_forecast", excluded)
        self.assertIn(
            "provider_parameter_to_confirmed_tornado_promotion",
            excluded,
        )

    def test_dwd_and_nws_stage_rules_are_distinct_adapter_normalization(self) -> None:
        stages = self.payload["alert_stage_rules"]
        self.assertEqual(stages["dwd"], "warning")
        self.assertEqual(stages["noaa_nws"][0], {"match": "warning", "stage": "warning"})
        self.assertEqual(stages["noaa_nws"][-1], {"match": "otherwise", "stage": "unspecified"})

    def test_match_scope_distinguishes_explicit_from_contextual(self) -> None:
        scopes = self.payload["hazard_match_scope_rules"]
        self.assertIn("event or headline", scopes["explicit_event"])
        self.assertIn("description or instruction", scopes["contextual_text"])
        self.assertEqual(scopes["non_tornado_event"], "null")

    def test_core_invariants_remain_hard(self) -> None:
        invariants = set(self.payload["invariants"])
        for item in (
            "No new public capability is introduced.",
            "Provider ID is not a scoring axis.",
            "Profiles remain deny-only.",
            "Tornado Warning is not a confirmed tornado.",
            "Radar rotation is not a confirmed tornado.",
            "Waterspout remains distinct from tornado.",
        ):
            self.assertIn(item, invariants)


if __name__ == "__main__":
    unittest.main()
