"""Static contract test for P5-AVIATION-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN = json.loads(
    (ROOT / "docs" / "p5_aviation_intent_design.v1.json").read_text(encoding="utf-8")
)
MAPPING = json.loads(
    (ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json").read_text(encoding="utf-8")
)


class P5AviationIntentDesignContractTest(unittest.TestCase):
    def test_no_new_public_contract_is_designed(self) -> None:
        self.assertEqual(DESIGN["target_runtime"]["public_capability_count"], 227)
        self.assertEqual(
            sorted(DESIGN["public_contracts_preserved"]),
            [
                "aviation.airmet.us",
                "aviation.gairmet.us",
                "aviation.sigmet.international",
            ],
        )

    def test_context_contract_is_explicit(self) -> None:
        contract = DESIGN["context_contract"]
        self.assertEqual(contract["global"], "allowed")
        self.assertEqual(contract["bbox"], "allowed_event_geometry_filter")
        self.assertEqual(contract["point"], "fail_closed_requirements_not_met")
        self.assertEqual(contract["nearby"], "not_implicit")

    def test_point_fail_closed_is_non_retryable_before_provider_contact(self) -> None:
        point = DESIGN["point_fail_closed"]
        self.assertEqual(point["code"], "requirements_not_met")
        self.assertFalse(point["retryable"])
        self.assertFalse(point["provider_contact"])

    def test_bbox_empty_result_remains_success(self) -> None:
        bbox = DESIGN["bbox_semantics"]
        self.assertTrue(bbox["empty_result_is_success"])
        self.assertFalse(bbox["empty_result_is_outside_coverage"])
        self.assertEqual(bbox["routing_authority"], "context_filter")
        self.assertFalse(bbox["endpoint_reachability_is_coverage"])

    def test_existing_mapping_still_has_exactly_three_aviation_ids(self) -> None:
        ids = sorted(
            item for item in MAPPING["public_capabilities"]
            if item.startswith("aviation.")
        )
        self.assertEqual(ids, sorted(DESIGN["public_contracts_preserved"]))

    def test_core_invariants_are_recorded(self) -> None:
        invariants = set(DESIGN["invariants"])
        for expected in (
            "Point must not silently become Global.",
            "BBOX is an event geometry filter, not Nearby.",
            "Empty BBOX result is a valid successful feed.",
            "Altitude and validity fields remain preserved.",
            "Aviation source role remains preserved.",
            "Provider ID is not a scoring axis.",
        ):
            self.assertIn(expected, invariants)


if __name__ == "__main__":
    unittest.main()
