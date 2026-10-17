"""Implementation regression tests for P5-SPACE-40."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
DRAFT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
SWPC_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_swpc.py"
CONSUMER_API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"
LAB_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab.js"
LOADER_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab-dev-loader.js"


class P5SpaceImplementationTest(unittest.TestCase):
    """Lock the implemented P5-SPACE-40 contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
        cls.swpc = SWPC_PATH.read_text(encoding="utf-8")
        cls.consumer_api = CONSUMER_API_PATH.read_text(encoding="utf-8")
        cls.const = CONST_PATH.read_text(encoding="utf-8")
        cls.lab = LAB_PATH.read_text(encoding="utf-8")
        cls.loader = LOADER_PATH.read_text(encoding="utf-8")

    def test_public_catalog_is_227_with_one_aurora_grid_intent(self) -> None:
        self.assertEqual(len(self.mapping["public_capabilities"]), 227)
        contract = self.mapping["public_capabilities"]["space.aurora.probability.grid"]
        self.assertEqual(contract["family"], "aurora")
        self.assertEqual(contract["phenomena"], ["aurora"])
        self.assertEqual(contract["resource_types"], ["data_file"])
        self.assertEqual(contract["strategy"], "single")
        self.assertIn("aurora", self.mapping["phenomena"])

    def test_runtime_and_draft_maps_are_identical(self) -> None:
        self.assertEqual(self.mapping, self.draft)

    def test_aurora_has_exactly_one_provider_neutral_candidate(self) -> None:
        self.assertEqual(
            self.mapping["providers"]["noaa_swpc"]["aurora_ovation_latest"],
            ["space.aurora.probability.grid"],
        )
        candidates = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if "space.aurora.probability.grid" in public_ids:
                    candidates.append(f"{provider_id}/{capability_id}")
        self.assertEqual(candidates, ["noaa_swpc/aurora_ovation_latest"])

    def test_aurora_candidate_semantics_match_design(self) -> None:
        provider = "noaa_swpc"
        capability = "aurora_ovation_latest"
        self.assertEqual(
            self.mapping["capability_resource_types"]["providers"][provider][capability],
            "data_file",
        )
        self.assertEqual(
            self.mapping["capability_source_semantics"]["providers"][provider][capability],
            {
                "data_origin": "space_weather_model",
                "measurement_method": "aurora_ovation_model",
            },
        )
        self.assertEqual(
            self.mapping["capability_observation_semantics"]["providers"][provider][capability],
            {"observation_kind": "forecast"},
        )
        coverage = self.mapping["capability_coverage_semantics"]["providers"][provider][capability]
        self.assertEqual(coverage["coverage_scope"], "global")
        self.assertEqual(coverage["coverage_evidence"], "machine_readable_runtime")
        self.assertEqual(coverage["routing_authority"], "advisory")
        self.assertEqual(coverage["coordinate_space"], "earth")
        self.assertFalse(coverage["endpoint_reachability_is_coverage"])

    def test_aurora_time_semantics_preserve_observation_and_forecast_time(self) -> None:
        time = self.mapping["capability_time_semantics"]["providers"]["noaa_swpc"][
            "aurora_ovation_latest"
        ]
        self.assertEqual(time["data_time"], "optional_runtime")
        self.assertEqual(time["valid_time"], "optional_runtime")
        self.assertIn('"Observation Time"', self.swpc)
        self.assertIn('"Forecast Time"', self.swpc)
        self.assertIn('"valid_time": forecast_time', self.swpc)
        self.assertIn('valid_time = _provider_time(candidate, "valid_time"', self.consumer_api)
        # NOAA OVATION: Beobachtungszeit und Vorhersagegueltigkeit bleiben
        # getrennt. Zeit ohne belegte UTC-Basis bleibt unbekannt.
        self.assertIn('"valid_time": valid_time', self.consumer_api)

    def test_swpc_provider_exposes_validated_ovation_data_file(self) -> None:
        self.assertIn('id="aurora_ovation_latest"', self.swpc)
        self.assertIn('render_mode="data_file"', self.swpc)
        self.assertIn("async def async_get_data_file(", self.swpc)
        self.assertIn("/json/ovation_aurora_latest.json", self.swpc)
        self.assertIn('"format": "json"', self.swpc)
        self.assertIn('"transport": "direct"', self.swpc)
        self.assertIn('"status": "integriert"', self.swpc)
        self.assertIn('"local_visibility_guarantee": False', self.swpc)

    def test_all_24_astronomy_candidates_have_global_point_coverage_contract(self) -> None:
        caps = self.mapping["providers"]["met_norway_astronomy"]
        coverage = self.mapping["capability_coverage_semantics"]["providers"][
            "met_norway_astronomy"
        ]
        self.assertEqual(len(caps), 24)
        self.assertEqual(set(caps), set(coverage))
        for capability in caps:
            item = coverage[capability]
            self.assertEqual(item["coverage_scope"], "global")
            self.assertEqual(item["coverage_evidence"], "static_provider_contract")
            self.assertEqual(item["routing_authority"], "advisory")
            self.assertEqual(item["coordinate_space"], "earth")
            self.assertFalse(item["endpoint_reachability_is_coverage"])

    def test_no_kp_or_generic_space_weather_intent_was_added(self) -> None:
        ids = set(self.mapping["public_capabilities"])
        self.assertFalse(any(".kp" in item or item.endswith(".kp") for item in ids))
        self.assertNotIn("space.weather.current", ids)
        self.assertNotIn("space.weather.severity", ids)

    def test_build_lab_and_loader_are_version_synchronized(self) -> None:
        # Keine statisch veraltete Versionsnummer aus einem alten P5-Test.
        import re
        def read_value(text, variable):
            match = re.search(
                r"\b" + re.escape(variable) + r'(?:: Final)?\s*=\s*"([^"]+)"',
                text,
            )
            self.assertIsNotNone(match, variable)
            return match.group(1)
        current = read_value(self.const, "DEV_BUILD_VERSION")
        loader_revision = read_value(self.const, "DEV_LOADER_REV")
        self.assertEqual(read_value(self.lab, "WR_LAB_BUILD_VERSION"), current)
        self.assertEqual(read_value(self.loader, "WR_LAB_BUILD_VERSION"), current)
        self.assertEqual(read_value(self.loader, "LOADER_REV"), loader_revision)


if __name__ == "__main__":
    unittest.main()
