"""Static contract test for the P3-WINDHAZ-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p3_windhaz_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"


class P3WindHazIntentDesignContractTest(unittest.TestCase):
    """Protect the provider-neutral P3-WINDHAZ-30 design."""

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
        ids = self.mapping["public_capabilities"]
        self.assertFalse(any("downburst" in item.casefold() for item in ids))
        self.assertFalse(any("windhaz" in item.casefold() for item in ids))

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
        self.assertEqual(
            primary["relevant_order"],
            ["downburst", "severe_thunderstorm", "windstorm"],
        )

    def test_wind_hazard_semantics_are_additive(self) -> None:
        field = self.design["additive_event_fields"]["wind_hazard_semantic_class"]
        self.assertEqual(
            set(field["values"]),
            {"official_wind_alert_event", "official_downburst_alert_event"},
        )
        self.assertTrue(field["independent_of_primary_hazard_type"])
        self.assertTrue(field["specific_downburst_precedence"])

    def test_match_scope_distinguishes_explicit_and_contextual(self) -> None:
        field = self.design["additive_event_fields"]["wind_hazard_match_scope"]
        self.assertEqual(
            set(field["values"]),
            {"explicit_event", "contextual_text"},
        )
        self.assertEqual(field["explicit_fields"], ["event", "headline"])
        self.assertEqual(field["contextual_fields"], ["description", "instruction"])

    def test_downburst_and_broad_wind_evidence_are_separate(self) -> None:
        evidence = self.design["evidence"]
        self.assertIn("downburst", evidence["downburst_specific"])
        self.assertIn("microburst", evidence["downburst_specific"])
        self.assertNotIn("damaging wind", evidence["downburst_specific"])
        self.assertIn("damaging wind", evidence["broad_wind"])
        self.assertFalse(evidence["isolated_wind_is_sufficient"])
        self.assertFalse(evidence["isolated_sturm_substring_is_sufficient"])

    def test_specialized_filter_does_not_require_primary_wind_label(self) -> None:
        filters = self.design["event_filter_additions"]
        self.assertEqual(
            set(filters["wind_hazard_semantic_classes"]),
            {"official_wind_alert_event", "official_downburst_alert_event"},
        )
        self.assertTrue(
            filters["specialized_filter_does_not_require_primary_wind_hazard_type"]
        )

    def test_numeric_p2_wind_contracts_are_preserved(self) -> None:
        self.assertEqual(len(self.design["numeric_wind_contracts_unchanged"]), 8)
        self.assertIn(
            "weather.point.wind_gusts",
            self.design["numeric_wind_contracts_unchanged"],
        )

    def test_observation_and_radar_promotions_are_excluded(self) -> None:
        excluded = set(self.design["excluded"])
        self.assertIn("observed_or_reported_wind_damage_event", excluded)
        self.assertIn("confirmed_downburst_observation_event", excluded)
        self.assertIn("downburst_radar_or_nowcast_signature", excluded)
        self.assertIn("numeric_wind_threshold_warning_inference", excluded)

    def test_core_routing_invariants_remain_explicit(self) -> None:
        invariants = set(self.design["invariants"])
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)
        self.assertIn("Coverage unknown remains unknown.", invariants)
        self.assertIn("P2-WIND numeric contracts remain unchanged.", invariants)


if __name__ == "__main__":
    unittest.main()
