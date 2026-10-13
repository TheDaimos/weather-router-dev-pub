"""Static contract test for P5-CIVIL-20 semantics."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS = json.loads(
    (ROOT / "docs" / "p5_civil_semantics.v1.json").read_text(encoding="utf-8")
)
MAPPING = json.loads(
    (ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json").read_text(encoding="utf-8")
)
CONSUMER = (
    ROOT / "custom_components" / "weather_router" / "consumer_api.py"
).read_text(encoding="utf-8")
MOWAS = (
    ROOT / "custom_components" / "weather_router" / "providers" / "bbk_mowas.py"
).read_text(encoding="utf-8")
NINA = (
    ROOT / "custom_components" / "weather_router" / "providers" / "nina_supplementary.py"
).read_text(encoding="utf-8")


class P5CivilSemanticsContractTest(unittest.TestCase):
    def test_context_contract_is_explicit(self) -> None:
        contract = SEMANTICS["context_contract"]
        self.assertEqual(contract["global"], "allowed")
        self.assertEqual(contract["bbox"], "allowed_event_geometry_filter")
        self.assertEqual(contract["point"], "fail_closed_requirements_not_met")
        self.assertEqual(contract["nearby"], "not_implicit")

    def test_current_providers_really_ignore_point_coordinates(self) -> None:
        self.assertIn("del latitude, longitude", MOWAS)
        self.assertIn("del latitude, longitude", NINA)
        point = SEMANTICS["point_fail_closed"]
        self.assertEqual(point["code"], "requirements_not_met")
        self.assertFalse(point["retryable"])
        self.assertFalse(point["provider_contact"])

    def test_aggregate_is_not_fallback_or_priority(self) -> None:
        agg = SEMANTICS["aggregation_semantics"]
        self.assertFalse(agg["aggregation_is_fallback"])
        self.assertFalse(agg["candidate_order_is_priority"])
        self.assertIn("for candidate in candidates:", CONSUMER)

    def test_source_provenance_is_required(self) -> None:
        self.assertIn('event["source_event_id"] = source_event_id', CONSUMER)
        self.assertIn('event["source_ref"] = candidate.provider.id', CONSUMER)
        self.assertTrue(
            SEMANTICS["aggregation_semantics"]["source_provenance_required"]
        )
        self.assertFalse(
            SEMANTICS["aggregation_semantics"][
                "provider_prefixed_event_id_is_global_incident_id"
            ]
        )

    def test_no_cross_channel_dedup_is_invented(self) -> None:
        self.assertFalse(
            SEMANTICS["aggregation_semantics"]["cross_channel_deduplication"]
        )

    def test_empty_and_degraded_semantics_are_explicit(self) -> None:
        agg = SEMANTICS["aggregation_semantics"]
        self.assertFalse(agg["successful_empty_source_is_error"])
        self.assertTrue(agg["partial_failure_can_be_degraded"])
        self.assertTrue(
            agg["successful_empty_aggregate_is_allowed_when_source_count_gt_zero"]
        )
        self.assertIn("degraded = bool(failures)", CONSUMER)

    def test_shared_coverage_contract_remains_dynamic_geometry(self) -> None:
        expected = SEMANTICS["coverage"]
        coverage = MAPPING["capability_coverage_semantics"]["providers"]
        for provider_id, capability_id in (
            ("bbk_mowas", "civil_protection_warnings_germany"),
            ("nina_flood", "flood_information_germany"),
            ("nina_katwarn", "katwarn_public_warnings"),
            ("nina_biwapp", "biwapp_public_warnings"),
        ):
            actual = coverage[provider_id][capability_id]
            for key, value in expected.items():
                self.assertEqual(actual[key], value)

    def test_no_synthetic_severity_contract(self) -> None:
        severity = SEMANTICS["severity_semantics"]
        self.assertFalse(severity["synthetic_common_severity"])
        self.assertFalse(severity["synthetic_urgency"])
        self.assertFalse(severity["synthetic_certainty"])

    def test_core_invariants_are_recorded(self) -> None:
        invariants = set(SEMANTICS["invariants"])
        for expected in (
            "Point must not silently become Global.",
            "Aggregation is not fallback.",
            "Warning channel is not a physical incident.",
            "No automatic cross-channel content deduplication is invented.",
            "Successful empty warning source is not a provider error.",
            "Source provenance must be preserved.",
            "Endpoint reachability is not coverage proof.",
        ):
            self.assertIn(expected, invariants)


if __name__ == "__main__":
    unittest.main()
