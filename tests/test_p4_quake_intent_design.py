"""Static contract test for P4-QUAKE-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p4_quake_intent_design.v1.json"


class P4QuakeIntentDesignContractTest(unittest.TestCase):
    """Protect the approved earthquake implementation design."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))

    def test_public_capability_count_stays_unchanged(self) -> None:
        self.assertEqual(self.payload["public_capability_count_target"], 226)
        self.assertEqual(self.payload["schema_changes"]["new_public_capabilities"], [])

    def test_two_existing_earthquake_contracts_stay_separate(self) -> None:
        contracts = self.payload["public_contracts"]
        self.assertEqual(len(contracts), 2)
        self.assertTrue(self.payload["no_shared_fallback_between_earthquake_feeds"]["enabled"])
        self.assertNotEqual(
            contracts["natural_hazards.earthquake.events"]["role"],
            contracts["natural_hazards.earthquake.significant_events"]["role"],
        )

    def test_additive_event_field_has_two_source_role_classes(self) -> None:
        event = self.payload["additive_event_field"]
        self.assertEqual(event["name"], "earthquake_semantics")
        self.assertEqual(
            set(event["semantic_classes"]),
            {
                "seismic_catalog_earthquake_event",
                "disaster_awareness_earthquake_event",
            },
        )
        self.assertTrue(event["preserve_existing_parameters"])

    def test_usgs_catalog_selection_is_capability_specific(self) -> None:
        mapping = self.payload["provider_mapping"]["usgs_earthquakes"]["catalog_selection"]
        self.assertEqual(mapping["earthquakes_past_day"], "all_day")
        self.assertEqual(
            mapping["significant_earthquakes_past_month"], "significant_month"
        )

    def test_related_roles_are_not_promoted_to_quake(self) -> None:
        mapping = self.payload["provider_mapping"]
        self.assertFalse(mapping["usgs_seismic_events"]["earthquake_semantics"])
        self.assertFalse(mapping["bmkg_tsunami"]["earthquake_semantics"])
        self.assertFalse(mapping["gdacs"]["primary_seismic_catalog"])

    def test_point_is_fail_closed_without_radius_semantics(self) -> None:
        point = self.payload["point_bbox_global"]["point"]
        self.assertEqual(point["action"], "reject_for_dedicated_earthquake_public_ids")
        self.assertEqual(point["unavailable_code"], "requirements_not_met")
        self.assertFalse(point["retryable"])
        self.assertTrue(point["future_radius_contract_out_of_scope"])

    def test_bbox_remains_event_point_filter_not_impact_area(self) -> None:
        bbox = self.payload["point_bbox_global"]["bbox"]
        self.assertEqual(bbox["diagnostic_mode"], "earthquake_event_point_bbox")
        self.assertFalse(bbox["point_geometry_is_impact_area"])

    def test_generic_severity_is_compatibility_only(self) -> None:
        severity = self.payload["generic_severity"]
        self.assertTrue(severity["keep_for_backward_compatibility"])
        self.assertFalse(severity["canonical_earthquake_semantics"])

    def test_diagnostics_are_quake_specific_but_provider_neutral(self) -> None:
        diagnostics = self.payload["diagnostics"]
        self.assertIn("earthquake_magnitude_range", diagnostics["resource_summary_add"])
        self.assertIn("earthquake_depth_km_range", diagnostics["resource_summary_add"])
        self.assertFalse(diagnostics["no_provider_priority"] is False)

    def test_runtime_target_is_next_version_without_loader_gap(self) -> None:
        target = self.payload["version_target"]
        self.assertEqual(target["weather_router"], "0.10.130 DEV")
        self.assertEqual(target["loader"], "0.10-loader-133")

    def test_hard_limits_are_explicit(self) -> None:
        limits = set(self.payload["hard_limits"])
        for expected in (
            "No new public capability.",
            "No fallback or aggregation between all-day and significant-month.",
            "No provider priority.",
            "No cross-provider deduplication.",
            "No cross-feed deduplication.",
            "No exact-coordinate Point match as nearby-earthquake semantics.",
            "No implicit radius.",
            "No endpoint reachability as coverage proof.",
        ):
            self.assertIn(expected, limits)


if __name__ == "__main__":
    unittest.main()
