"""Static contract test for the P3-HAIL-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p3_hail_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"


class P3HailIntentDesignContractTest(unittest.TestCase):
    """Protect the provider-neutral P3-HAIL-30 design."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))

    def test_no_new_public_capability_is_designed(self) -> None:
        self.assertEqual(self.design["public_capabilities_added"], 0)
        self.assertEqual(
            self.design["public_capability_count_before"],
            self.design["public_capability_count_after"],
        )
        public_ids = self.mapping["public_capabilities"]
        self.assertFalse(any("hail" in item.casefold() for item in public_ids))

    def test_existing_warning_transport_remains_aggregate(self) -> None:
        transport = self.design["public_transport"]
        self.assertEqual(transport["id"], "weather.warning.official")
        self.assertEqual(transport["strategy"], "aggregate")
        self.assertEqual(
            transport["candidates"],
            [
                "dwd/official_weather_warnings",
                "noaa_nws/official_weather_alerts",
            ],
        )

    def test_primary_hazard_normalization_is_not_reordered(self) -> None:
        primary = self.design["primary_hazard_type"]
        self.assertFalse(primary["change"])
        self.assertFalse(primary["reorder_patterns"])

    def test_hail_semantic_class_is_additive_and_primary_label_independent(self) -> None:
        field = self.design["additive_event_fields"]["hail_semantic_class"]
        self.assertEqual(field["values"], ["official_hail_alert_event"])
        self.assertTrue(field["independent_of_primary_hazard_type"])

    def test_hail_match_scope_distinguishes_explicit_and_contextual(self) -> None:
        field = self.design["additive_event_fields"]["hail_match_scope"]
        self.assertEqual(
            set(field["values"]),
            {"explicit_event", "contextual_text"},
        )
        self.assertEqual(field["explicit_fields"], ["event", "headline"])
        self.assertEqual(field["contextual_fields"], ["description", "instruction"])
        self.assertTrue(field["explicit_precedence"])

    def test_existing_alert_stage_is_reused(self) -> None:
        stage = self.design["additive_event_fields"]["alert_stage"]
        self.assertTrue(stage["reuse_existing_field"])
        self.assertEqual(
            set(stage["values"]),
            {"warning", "watch", "outlook", "statement", "unspecified"},
        )

    def test_specialized_hail_filter_does_not_require_primary_hail_label(self) -> None:
        filters = self.design["event_filter_additions"]
        self.assertEqual(
            filters["hail_semantic_classes"],
            ["official_hail_alert_event"],
        )
        self.assertTrue(
            filters["specialized_hail_filter_does_not_require_hazard_type_hail"]
        )

    def test_consumer_preservation_is_explicit(self) -> None:
        preservation = self.design["preservation"]
        self.assertEqual(
            preservation["consumer_normalization_fields"],
            ["hail_semantic_class", "hail_match_scope", "alert_stage"],
        )
        self.assertIn(
            "hail_semantic_classes",
            preservation["resource_diagnostic_fields"],
        )
        self.assertIn(
            "hail_match_scopes",
            preservation["resource_diagnostic_fields"],
        )

    def test_non_warning_hail_classes_remain_excluded(self) -> None:
        excluded = set(self.design["excluded"])
        self.assertIn("observed_or_reported_hail_event", excluded)
        self.assertIn("hail_size_measurement_or_forecast", excluded)
        self.assertIn("radar_hail_signature", excluded)
        self.assertIn("hail_probability_forecast", excluded)

    def test_core_routing_invariants_remain_explicit(self) -> None:
        invariants = set(self.design["invariants"])
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)
        self.assertIn("Coverage unknown remains unknown.", invariants)
        self.assertIn("Endpoint reachability is not coverage proof.", invariants)


if __name__ == "__main__":
    unittest.main()
