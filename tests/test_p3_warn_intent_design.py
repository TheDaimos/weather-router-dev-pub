"""Static contract test for the P3-WARN-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p3_warn_intent_design.v1.json"


class P3WarnIntentDesignContractTest(unittest.TestCase):
    """Protect the warning intent design until implementation changes it explicitly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.intent = cls.payload["public_intents"]["weather.warning.official"]

    def test_no_new_public_capability_is_introduced(self) -> None:
        self.assertEqual(self.payload["public_capability_count_before"], 226)
        self.assertEqual(self.payload["public_capabilities_added"], 0)
        self.assertEqual(self.payload["public_capability_count_after"], 226)
        self.assertEqual(self.intent["action"], "reuse_existing")

    def test_candidate_set_remains_exactly_dwd_and_nws(self) -> None:
        self.assertEqual(
            self.intent["candidates"],
            [
                "dwd/official_weather_warnings",
                "noaa_nws/official_weather_alerts",
            ],
        )
        self.assertEqual(self.intent["candidate_count"], 2)

    def test_existing_aggregate_and_event_filter_contract_is_preserved(self) -> None:
        self.assertEqual(self.intent["strategy"], "aggregate")
        self.assertEqual(self.intent["resource_type"], "hazard_feed")
        self.assertEqual(
            self.intent["filters"]["hazard_types"],
            "event_filter.hazard_types",
        )
        self.assertEqual(
            self.intent["filters"]["severities"],
            "event_filter.severities",
        )
        self.assertEqual(self.intent["source_provenance"], "preserve_per_event")

    def test_no_provider_priority_or_cross_provider_dedup_is_designed(self) -> None:
        self.assertFalse(self.intent["provider_priority"])
        self.assertFalse(self.intent["strongest_warning_wins"])
        self.assertFalse(self.intent["cross_provider_deduplication"])
        self.assertEqual(
            self.payload["aggregation_policy"]["deduplication"],
            "none_in_p3_warn_40",
        )

    def test_point_requires_real_spatial_evidence(self) -> None:
        point = self.payload["spatial_policy"]["point"]
        self.assertTrue(point["geometry_or_provider_point_proof_required"])
        self.assertIn("machine-readable", point["rule"])

    def test_bbox_missing_geometry_is_fail_closed(self) -> None:
        bbox = self.payload["spatial_policy"]["bbox"]
        self.assertTrue(bbox["geometry_required"])
        self.assertEqual(bbox["missing_geometry"], "exclude_from_bbox_match")
        self.assertEqual(
            self.payload["noaa_nws_target"]["missing_bbox_geometry"],
            "exclude",
        )

    def test_dwd_requires_real_geometry_before_context_coverage_claim(self) -> None:
        dwd = self.payload["dwd_target"]
        self.assertIn("official DWD CAP/status geometry", dwd["implementation_requirement"])
        self.assertIn(
            "claim runtime_event_geometry without actual geometry",
            dwd["forbidden"],
        )
        self.assertIn(
            "treat endpoint reachability as coverage",
            dwd["forbidden"],
        )

    def test_global_context_does_not_require_geometry(self) -> None:
        global_policy = self.payload["spatial_policy"]["global"]
        self.assertFalse(global_policy["geometry_required"])

    def test_missing_cap_fields_remain_missing(self) -> None:
        self.assertEqual(
            self.payload["event_contract"]["missing_optional_fields"],
            "remain absent_or_null",
        )

    def test_design_preserves_core_invariants(self) -> None:
        invariants = set(self.payload["invariants"])
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)
        self.assertIn(
            "Missing event geometry cannot prove point/bbox relevance.",
            invariants,
        )
        self.assertIn(
            "Endpoint reachability is not coverage evidence.",
            invariants,
        )

    def test_design_does_not_encode_preferred_provider_or_routing_score(self) -> None:
        raw = DESIGN_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("routing_score", raw)


if __name__ == "__main__":
    unittest.main()
