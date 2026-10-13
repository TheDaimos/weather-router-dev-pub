"""Regression coverage for P5-CIVIL-40 implementation."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONSUMER = (
    ROOT / "custom_components" / "weather_router" / "consumer_api.py"
).read_text(encoding="utf-8")
CONST = (
    ROOT / "custom_components" / "weather_router" / "const.py"
).read_text(encoding="utf-8")
LAB = (
    ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab.js"
).read_text(encoding="utf-8")
LOADER = (
    ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab-dev-loader.js"
).read_text(encoding="utf-8")
MAPPING = json.loads(
    (ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json").read_text(encoding="utf-8")
)


from wr_public_version_contract import assert_current_version_surfaces

class P5CivilImplementationTest(unittest.TestCase):
    def test_exact_civil_public_id_guard_is_declared(self) -> None:
        self.assertIn("_CIVIL_PROTECTION_PUBLIC_IDS = frozenset(", CONSUMER)
        self.assertIn('"civil_protection.warning.official"', CONSUMER)

    def test_context_supported_marks_civil_point_unsupported(self) -> None:
        start = CONSUMER.index("def _context_supported")
        end = CONSUMER.index("def _requirements_match", start)
        block = CONSUMER[start:end]
        self.assertIn(
            "candidate.public_id in _CIVIL_PROTECTION_PUBLIC_IDS",
            block,
        )
        self.assertIn('context["type"] == "point"', block)
        self.assertIn("return False", block)

    def test_public_point_guard_precedes_aggregate_resolution(self) -> None:
        guard = CONSUMER.index("Civil-Point-Abfragen benötigen")
        aggregate = CONSUMER.index(
            "payload, provider_result, provenance, degraded = await _resolve_aggregate_hazard",
            guard,
        )
        self.assertLess(guard, aggregate)
        block = CONSUMER[max(0, guard - 900):guard + 900]
        self.assertIn('"requirements_not_met"', block)
        self.assertIn("retryable=False", block)
        self.assertIn("trace.stage_end", block)
        self.assertIn("return", block)

    def test_point_guard_rejects_candidates_without_attempting_them(self) -> None:
        guard = CONSUMER.index("Civil-Point-Abfragen benötigen")
        block = CONSUMER[max(0, guard - 1200):guard + 900]
        self.assertIn(
            'result="rejected"',
            block,
        )
        self.assertIn(
            'reason="requirements_not_met"',
            block,
        )
        self.assertNotIn("candidate_attempt(", block)
        self.assertNotIn("candidate_provider_contact(", block)

    def test_global_and_bbox_generic_paths_remain_available(self) -> None:
        self.assertIn(
            'if render_mode in {"hazard_feed", "event_feed"}:\n        return ["global", "point", "bbox"]',
            CONSUMER,
        )
        self.assertIn('elif context["type"] == "bbox":', CONSUMER)
        self.assertIn('kwargs["bbox"] = (', CONSUMER)

    def test_public_catalog_remains_227_and_aggregate(self) -> None:
        self.assertEqual(len(MAPPING["public_capabilities"]), 227)
        public = MAPPING["public_capabilities"]["civil_protection.warning.official"]
        self.assertEqual(public["strategy"], "aggregate")
        self.assertEqual(public["resource_types"], ["hazard_feed"])

    def test_version_surfaces_are_010140_loader143(self) -> None:
        assert_current_version_surfaces(self, CONST, LAB, LOADER)


if __name__ == "__main__":
    unittest.main()
