"""Independent static acceptance for P5-AVIATION-50."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
DRAFT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
DESIGN_PATH = ROOT / "docs" / "p5_aviation_intent_design.v1.json"
PROVIDER_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "aviation_weather.py"
CONSUMER_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"
LAB_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab.js"
LOADER_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab-dev-loader.js"


from wr_public_version_contract import assert_current_version_surfaces

class P5AviationStaticAcceptanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.provider = PROVIDER_PATH.read_text(encoding="utf-8")
        cls.consumer = CONSUMER_PATH.read_text(encoding="utf-8")
        cls.const = CONST_PATH.read_text(encoding="utf-8")
        cls.lab = LAB_PATH.read_text(encoding="utf-8")
        cls.loader = LOADER_PATH.read_text(encoding="utf-8")

    def _candidates_for(self, public_id: str) -> list[str]:
        found: list[str] = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    found.append(f"{provider_id}/{capability_id}")
        return found

    def test_01_catalog_remains_227_with_exact_three_aviation_ids(self) -> None:
        self.assertEqual(len(self.mapping["public_capabilities"]), 227)
        ids = sorted(
            item for item in self.mapping["public_capabilities"]
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

    def test_02_each_aviation_intent_remains_single_candidate(self) -> None:
        expected = {
            "aviation.airmet.us": "aviation_weather/us_airsigmet_current",
            "aviation.gairmet.us": "aviation_weather/us_gairmet_current",
            "aviation.sigmet.international":
                "aviation_weather/international_sigmet_worldwide",
        }
        for public_id, candidate in expected.items():
            self.assertEqual(self._candidates_for(public_id), [candidate])

    def test_03_all_resources_remain_hazard_feeds(self) -> None:
        for public_id in self.design["public_contracts_preserved"]:
            self.assertEqual(
                self.mapping["public_capabilities"][public_id]["resource_types"],
                ["hazard_feed"],
            )

    def test_04_point_fails_closed_before_provider_fetch(self) -> None:
        guard = self.consumer.index(
            "candidate.public_id in _AVIATION_PUBLIC_IDS"
        )
        fetch = self.consumer.index(
            'fetch = getattr(candidate.provider, "async_get_hazard_feed", None)',
            guard,
        )
        block = self.consumer[guard:fetch]
        self.assertIn('"requirements_not_met"', block)
        self.assertIn("retryable=False", block)
        self.assertIn("BBOX oder Global", block)

    def test_05_global_and_bbox_paths_are_preserved(self) -> None:
        contract = self.design["context_contract"]
        self.assertEqual(contract["global"], "allowed")
        self.assertEqual(contract["bbox"], "allowed_event_geometry_filter")
        self.assertIn('kwargs["bbox"] = (', self.consumer)

    def test_06_no_nearby_or_implicit_radius_is_added(self) -> None:
        self.assertEqual(self.design["context_contract"]["nearby"], "not_implicit")
        aviation_guard = self.consumer[
            self.consumer.index("candidate.public_id in _AVIATION_PUBLIC_IDS"):
            self.consumer.index(
                "candidate.public_id in _EARTHQUAKE_PUBLIC_IDS",
                self.consumer.index("candidate.public_id in _AVIATION_PUBLIC_IDS"),
            )
        ]
        self.assertNotIn("radius", aviation_guard.casefold())
        self.assertNotIn("nearby", aviation_guard.casefold())

    def test_07_empty_feed_is_valid_and_not_outside_coverage(self) -> None:
        self.assertTrue(self.design["bbox_semantics"]["empty_result_is_success"])
        self.assertFalse(
            self.design["bbox_semantics"]["empty_result_is_outside_coverage"]
        )
        self.assertIn('"events": events', self.provider)
        self.assertIn('"event_count": len(events)', self.provider)

    def test_08_altitude_validity_and_source_role_are_preserved(self) -> None:
        for token in (
            '"effective": props.get("validTimeFrom")',
            '"expires": props.get("validTimeTo")',
            '"altitude_low_ft": props.get("altitudeLow1")',
            '"altitude_high_ft":',
            '"source_semantics": "official_aviation_warning"',
            '"aviation_only": True',
        ):
            self.assertIn(token, self.provider)

    def test_09_no_generic_severity_is_invented(self) -> None:
        self.assertIn('"severity": "unknown"', self.provider)
        self.assertIn('"generic_severity_created": false', DESIGN_PATH.read_text(encoding="utf-8").lower())

    def test_10_coverage_semantics_stay_context_filter(self) -> None:
        coverage = self.mapping["capability_coverage_semantics"]["providers"]["aviation_weather"]
        self.assertEqual(len(coverage), 3)
        for item in coverage.values():
            self.assertEqual(item["coverage_scope"], "dynamic")
            self.assertEqual(item["coverage_evidence"], "runtime_event_geometry")
            self.assertEqual(item["routing_authority"], "context_filter")
            self.assertEqual(item["coordinate_space"], "earth")
            self.assertFalse(item["endpoint_reachability_is_coverage"])

    def test_11_runtime_and_draft_maps_remain_identical(self) -> None:
        self.assertEqual(self.mapping, self.draft)

    def test_12_version_surfaces_are_010138_loader141(self) -> None:
        assert_current_version_surfaces(self, self.const, self.lab, self.loader)


if __name__ == "__main__":
    unittest.main()
