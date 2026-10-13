"""Static contract test for P5-CIVIL-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN = json.loads(
    (ROOT / "docs" / "p5_civil_intent_design.v1.json").read_text(encoding="utf-8")
)
MAPPING = json.loads(
    (ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json").read_text(encoding="utf-8")
)


class P5CivilIntentDesignContractTest(unittest.TestCase):
    def test_no_new_public_contract_is_designed(self) -> None:
        self.assertEqual(DESIGN["target_runtime"]["public_capability_count"], 227)
        self.assertEqual(
            DESIGN["public_contract"]["id"],
            "civil_protection.warning.official",
        )
        self.assertEqual(DESIGN["public_contract"]["candidate_count"], 4)

    def test_public_contract_remains_aggregate_hazard_feed(self) -> None:
        public = MAPPING["public_capabilities"]["civil_protection.warning.official"]
        self.assertEqual(public["strategy"], "aggregate")
        self.assertEqual(public["resource_types"], ["hazard_feed"])
        self.assertEqual(DESIGN["public_contract"]["strategy"], "aggregate")

    def test_context_contract_is_explicit(self) -> None:
        contract = DESIGN["context_contract"]
        self.assertEqual(contract["global"], "allowed")
        self.assertEqual(contract["bbox"], "allowed_event_geometry_filter")
        self.assertEqual(
            contract["point"],
            "public_intent_fail_closed_requirements_not_met",
        )
        self.assertEqual(contract["nearby"], "not_implicit")

    def test_point_guard_is_before_aggregate_resolution(self) -> None:
        guard = DESIGN["point_guard"]
        self.assertEqual(guard["level"], "public_intent_before_aggregate_resolution")
        self.assertEqual(guard["code"], "requirements_not_met")
        self.assertFalse(guard["retryable"])
        self.assertFalse(guard["provider_contact"])
        self.assertFalse(guard["aggregate_resolution_started"])

    def test_existing_candidate_count_remains_four(self) -> None:
        found = []
        for provider_id, capabilities in MAPPING["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if "civil_protection.warning.official" in public_ids:
                    found.append(f"{provider_id}/{capability_id}")
        self.assertEqual(len(found), 4)

    def test_aggregation_semantics_are_preserved(self) -> None:
        preserved = DESIGN["preserved"]
        self.assertTrue(preserved["aggregate_provenance"])
        self.assertTrue(preserved["degraded_partial_failure"])
        self.assertTrue(preserved["successful_empty_source"])
        self.assertFalse(preserved["cross_channel_deduplication"])
        self.assertTrue(preserved["cross_domain_nina_flood"])

    def test_core_invariants_are_recorded(self) -> None:
        invariants = set(DESIGN["invariants"])
        for expected in (
            "No new public civil capability.",
            "Point must not silently become Global.",
            "Point must fail before aggregate provider resolution.",
            "Aggregation is not fallback.",
            "No cross-channel deduplication is introduced.",
            "Source provenance remains preserved.",
        ):
            self.assertIn(expected, invariants)


if __name__ == "__main__":
    unittest.main()
