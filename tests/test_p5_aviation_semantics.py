"""Static contract test for P5-AVIATION-20 semantics."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS = json.loads(
    (ROOT / "docs" / "p5_aviation_semantics.v1.json").read_text(encoding="utf-8")
)
MAPPING = json.loads(
    (ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json").read_text(encoding="utf-8")
)
PROVIDER = (
    ROOT / "custom_components" / "weather_router" / "providers" / "aviation_weather.py"
).read_text(encoding="utf-8")


class P5AviationSemanticsContractTest(unittest.TestCase):
    def test_shared_semantics_match_runtime_contract(self) -> None:
        source = MAPPING["capability_source_semantics"]["providers"]["aviation_weather"]
        observation = MAPPING["capability_observation_semantics"]["providers"]["aviation_weather"]
        coverage = MAPPING["capability_coverage_semantics"]["providers"]["aviation_weather"]
        for capability_id in source:
            self.assertEqual(source[capability_id]["data_origin"], "warning_authority")
            self.assertEqual(source[capability_id]["measurement_method"], "aviation_advisory_feed")
            self.assertEqual(observation[capability_id]["observation_kind"], "warning_event")
            self.assertEqual(coverage[capability_id]["coverage_scope"], "dynamic")
            self.assertEqual(coverage[capability_id]["coverage_evidence"], "runtime_event_geometry")
            self.assertEqual(coverage[capability_id]["routing_authority"], "context_filter")
            self.assertFalse(coverage[capability_id]["endpoint_reachability_is_coverage"])

    def test_provider_preserves_validity_and_altitude_fields(self) -> None:
        for field in (
            '"effective":',
            '"onset":',
            '"expires":',
            '"ends":',
            '"altitude_low_ft":',
            '"altitude_high_ft":',
        ):
            self.assertIn(field, PROVIDER)

    def test_empty_feed_is_valid_provider_result(self) -> None:
        self.assertIn('"events": events', PROVIDER)
        self.assertIn('"event_count": len(events)', PROVIDER)
        self.assertFalse(SEMANTICS["semantics"]["empty_feed_is_outside_coverage"])
        self.assertFalse(SEMANTICS["semantics"]["empty_feed_is_provider_error"])

    def test_bbox_is_event_filter_not_nearby(self) -> None:
        self.assertIn("geometry_intersects_bbox", PROVIDER)
        self.assertFalse(SEMANTICS["semantics"]["bbox_is_nearby"])

    def test_no_generic_severity_or_provider_priority(self) -> None:
        self.assertFalse(SEMANTICS["semantics"]["generic_severity_created"])
        self.assertFalse(SEMANTICS["semantics"]["provider_priority"])
        self.assertFalse(SEMANTICS["semantics"]["cross_product_fallback"])

    def test_hard_invariants_are_recorded(self) -> None:
        invariants = set(SEMANTICS["invariants"])
        for item in (
            "SIGMET is not AIRMET.",
            "AIRMET is not G-AIRMET.",
            "Aviation warning is not a general public warning.",
            "Altitude bands must be preserved.",
            "Validity times must be preserved.",
            "Empty feed is not outside coverage.",
            "Endpoint reachability is not coverage proof.",
            "BBOX filtering is not Nearby semantics.",
            "Provider ID is not a scoring axis.",
        ):
            self.assertIn(item, invariants)


if __name__ == "__main__":
    unittest.main()
