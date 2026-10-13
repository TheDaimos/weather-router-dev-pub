"""Regression coverage for P5-AVIATION-40 implementation."""

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

class P5AviationImplementationTest(unittest.TestCase):
    def test_exact_aviation_public_id_set_is_declared(self) -> None:
        for public_id in (
            "aviation.airmet.us",
            "aviation.gairmet.us",
            "aviation.sigmet.international",
        ):
            self.assertIn(f'"{public_id}"', CONSUMER)
        self.assertIn("_AVIATION_PUBLIC_IDS = frozenset(", CONSUMER)

    def test_aviation_point_fails_closed_before_provider_fetch(self) -> None:
        guard = CONSUMER.index(
            'candidate.public_id in _AVIATION_PUBLIC_IDS'
        )
        fetch = CONSUMER.index(
            'fetch = getattr(candidate.provider, "async_get_hazard_feed", None)',
            guard,
        )
        self.assertLess(guard, fetch)
        block = CONSUMER[guard:fetch]
        self.assertIn('"requirements_not_met"', block)
        self.assertIn("retryable=False", block)
        self.assertIn("BBOX oder Global", block)

    def test_global_and_bbox_paths_remain_available(self) -> None:
        self.assertIn('elif context["type"] == "bbox":', CONSUMER)
        self.assertIn('kwargs["bbox"] = (', CONSUMER)
        self.assertIn('if mode == "hazard_feed":', CONSUMER)

    def test_public_catalog_remains_227_with_three_aviation_ids(self) -> None:
        self.assertEqual(len(MAPPING["public_capabilities"]), 227)
        ids = sorted(
            item for item in MAPPING["public_capabilities"]
            if item.startswith("aviation.")
        )
        self.assertEqual(
            ids,
            [
                "aviation.airmet.us",
                "aviation.gairmet.us",
                "aviation.sigmet.international",
            ],
        )

    def test_version_surfaces_are_010138_loader141(self) -> None:
        assert_current_version_surfaces(self, CONST, LAB, LOADER)


if __name__ == "__main__":
    unittest.main()
