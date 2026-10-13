"""Static contract test for the P5-AVIATION-10 inventory."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = json.loads(
    (ROOT / "docs" / "p5_aviation_inventory.v1.json").read_text(encoding="utf-8")
)
MAPPING = json.loads(
    (ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json").read_text(encoding="utf-8")
)
REGISTRY = json.loads(
    (ROOT / "custom_components" / "weather_router" / "providers" / "registry.json").read_text(encoding="utf-8")
)["providers"]
PROVIDER = (
    ROOT / "custom_components" / "weather_router" / "providers" / "aviation_weather.py"
).read_text(encoding="utf-8")


class P5AviationInventoryContractTest(unittest.TestCase):
    def test_exactly_three_public_aviation_contracts_exist(self) -> None:
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
        self.assertEqual(INVENTORY["aviation_public_capability_count"], 3)

    def test_single_aviation_provider_is_default_disabled(self) -> None:
        entry = next(item for item in REGISTRY if item["module"] == "aviation_weather")
        self.assertEqual(entry["class"], "AviationWeatherProvider")
        self.assertEqual(entry["domains"], ["aviation"])
        self.assertFalse(entry["default_enabled"])

    def test_each_public_contract_has_one_candidate(self) -> None:
        expected = {
            "aviation.airmet.us": "aviation_weather/us_airsigmet_current",
            "aviation.gairmet.us": "aviation_weather/us_gairmet_current",
            "aviation.sigmet.international":
                "aviation_weather/international_sigmet_worldwide",
        }
        for public_id, candidate in expected.items():
            found = []
            for provider_id, capabilities in MAPPING["providers"].items():
                for capability_id, public_ids in capabilities.items():
                    if public_id in public_ids:
                        found.append(f"{provider_id}/{capability_id}")
            self.assertEqual(found, [candidate])

    def test_all_aviation_resources_are_hazard_feeds(self) -> None:
        for public_id in (
            "aviation.airmet.us",
            "aviation.gairmet.us",
            "aviation.sigmet.international",
        ):
            self.assertEqual(
                MAPPING["public_capabilities"][public_id]["resource_types"],
                ["hazard_feed"],
            )

    def test_shared_source_and_coverage_semantics_are_explicit(self) -> None:
        source = MAPPING["capability_source_semantics"]["providers"]["aviation_weather"]
        observation = MAPPING["capability_observation_semantics"]["providers"]["aviation_weather"]
        coverage = MAPPING["capability_coverage_semantics"]["providers"]["aviation_weather"]
        self.assertEqual(len(source), 3)
        self.assertEqual(set(source), set(observation))
        self.assertEqual(set(source), set(coverage))
        for capability_id in source:
            self.assertEqual(source[capability_id]["data_origin"], "warning_authority")
            self.assertEqual(
                source[capability_id]["measurement_method"],
                "aviation_advisory_feed",
            )
            self.assertEqual(
                observation[capability_id]["observation_kind"],
                "warning_event",
            )
            self.assertEqual(coverage[capability_id]["coverage_scope"], "dynamic")
            self.assertEqual(
                coverage[capability_id]["coverage_evidence"],
                "runtime_event_geometry",
            )
            self.assertEqual(
                coverage[capability_id]["routing_authority"],
                "context_filter",
            )
            self.assertFalse(
                coverage[capability_id]["endpoint_reachability_is_coverage"]
            )

    def test_aviation_only_semantics_are_preserved_in_provider(self) -> None:
        self.assertIn('"source_semantics": "official_aviation_warning"', PROVIDER)
        self.assertIn('"aviation_only": True', PROVIDER)
        self.assertIn("not a general public warning", PROVIDER)
        self.assertIn('"altitude_low_ft"', PROVIDER)
        self.assertIn('"altitude_high_ft"', PROVIDER)

    def test_core_invariants_are_recorded(self) -> None:
        invariants = set(INVENTORY["invariants"])
        for item in (
            "Aviation warning is not a general public warning.",
            "SIGMET is not AIRMET.",
            "AIRMET is not G-AIRMET.",
            "Altitude bands must be preserved when provided.",
            "Validity times must be preserved when provided.",
            "Endpoint reachability is not coverage proof.",
            "Provider ID is not a scoring axis.",
        ):
            self.assertIn(item, invariants)


if __name__ == "__main__":
    unittest.main()
