"""Static contract test for the P3-WARN-20 semantic classification."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p3_warn_semantics.v1.json"


class P3WarnSemanticsContractTest(unittest.TestCase):
    """Keep P3-WARN-20 warning-event boundaries explicit."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
        cls.candidates = cls.payload["candidate_classification"]

    def test_inventory_count_is_preserved(self) -> None:
        self.assertEqual(len(self.candidates), 2)
        self.assertEqual(
            {(item["provider"], item["capability"]) for item in self.candidates},
            {
                ("dwd", "official_weather_warnings"),
                ("noaa_nws", "official_weather_alerts"),
            },
        )

    def test_both_candidates_share_official_warning_event_semantics(self) -> None:
        for item in self.candidates:
            self.assertEqual(item["semantic_class"], "official_weather_warning_event_feed")
            self.assertEqual(item["resource_type"], "hazard_feed")
            self.assertEqual(item["data_origin"], "warning_authority")
            self.assertEqual(item["measurement_method"], "official_weather_warning_feed")
            self.assertEqual(item["observation_kind"], "warning_event")

    def test_dwd_context_coverage_is_not_claimed_as_runtime_proven(self) -> None:
        dwd = next(item for item in self.candidates if item["provider"] == "dwd")
        self.assertEqual(dwd["event_geometry"], "absent_warncell_id_only")
        self.assertEqual(dwd["context_filtering"], "not_applied")
        self.assertEqual(dwd["runtime_proven_coverage"], "not_proven")

        coverage = self.payload["coverage_rules"]["dwd"]
        self.assertEqual(coverage["runtime_evidence"]["geometry"], "null")
        self.assertEqual(
            coverage["runtime_evidence"]["geometry_status"],
            "warncell_id_only",
        )
        self.assertFalse(coverage["runtime_evidence"]["point_bbox_filtering"])

    def test_nws_runtime_context_filter_is_preserved(self) -> None:
        nws = next(item for item in self.candidates if item["provider"] == "noaa_nws")
        self.assertEqual(nws["event_geometry"], "geojson_when_published")
        self.assertEqual(
            nws["context_filtering"],
            "point_parameter_and_bbox_geometry_filter",
        )
        self.assertEqual(nws["runtime_proven_coverage"], "proven")

    def test_missing_cap_fields_must_not_be_invented(self) -> None:
        contract = self.payload["event_contract"]
        self.assertEqual(
            contract["missing_optional_fields"],
            "remain_null_or_absent_not_invented",
        )
        self.assertIn("urgency", contract["optional_fields"])
        self.assertIn("certainty", contract["optional_fields"])
        self.assertIn("geometry", contract["optional_fields"])

    def test_severity_is_coarse_normalization_not_threshold_identity(self) -> None:
        rules = self.payload["severity_rules"]
        self.assertEqual(
            rules["canonical_values"],
            ["minor", "moderate", "severe", "extreme", "unknown"],
        )
        self.assertFalse(rules["thresholds_equivalent_across_authorities"])
        self.assertTrue(rules["missing_precision_must_not_be_invented"])

    def test_aggregate_does_not_encode_priority_or_unproven_dedup(self) -> None:
        rules = self.payload["aggregation_rules"]
        self.assertEqual(rules["current_public_strategy"], "aggregate")
        self.assertTrue(rules["preserve_per_event_provenance"])
        self.assertFalse(rules["provider_priority_allowed"])
        self.assertFalse(rules["strongest_warning_wins_allowed"])
        self.assertEqual(
            rules["cross_provider_deduplication"],
            "not_proven_not_allowed_without_identity_rule",
        )

    def test_empty_feed_is_valid_no_warning_state(self) -> None:
        rules = self.payload["empty_feed_rules"]
        self.assertTrue(rules["successful_empty_feed_is_valid_no_active_warning_state"])
        self.assertTrue(rules["empty_feed_is_not_automatically_temporarily_unavailable"])

    def test_semantic_boundaries_remain_hard(self) -> None:
        rules = self.payload["rules"]
        self.assertTrue(rules["warning_is_not_probability"])
        self.assertTrue(rules["warning_is_not_thunderstorm_cell"])
        self.assertTrue(rules["warning_is_not_lightning_observation"])
        self.assertTrue(rules["hazard_feed_is_not_numeric_measurement"])
        self.assertTrue(rules["unproven_coverage_is_not_hard_coverage"])
        self.assertTrue(rules["warncell_id_without_machine_mapping_is_not_runtime_event_geometry"])
        self.assertTrue(rules["provider_id_is_not_scoring_axis"])
        self.assertTrue(rules["profiles_are_deny_only"])

    def test_no_provider_priority_or_scoring_decision_is_encoded(self) -> None:
        raw = SEMANTICS_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("routing_score", raw)


if __name__ == "__main__":
    unittest.main()
