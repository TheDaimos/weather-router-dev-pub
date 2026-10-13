"""Independent static acceptance for P5-POLLEN-50."""

from __future__ import annotations

import json
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "docs" / "p5_pollen_intent_design.v1.json"
RUNTIME_MAP = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
DRAFT_MAP = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
REGISTRY = ROOT / "custom_components" / "weather_router" / "providers" / "registry.json"
PROVIDER = ROOT / "custom_components" / "weather_router" / "providers" / "open_meteo_pollen.py"
CONSUMER = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
CONST = ROOT / "custom_components" / "weather_router" / "const.py"
LAB = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab.js"
LOADER = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab-dev-loader.js"

PUBLIC = {
    "pollen.alder": "alder_pollen",
    "pollen.birch": "birch_pollen",
    "pollen.grass": "grass_pollen",
    "pollen.mugwort": "mugwort_pollen",
    "pollen.olive": "olive_pollen",
    "pollen.ragweed": "ragweed_pollen",
}

class P5PollenStaticAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = json.loads(DESIGN.read_text(encoding="utf-8"))
        cls.runtime = json.loads(RUNTIME_MAP.read_text(encoding="utf-8"))
        cls.draft = json.loads(DRAFT_MAP.read_text(encoding="utf-8"))
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        cls.provider = PROVIDER.read_text(encoding="utf-8")
        cls.consumer = CONSUMER.read_text(encoding="utf-8")
        cls.const = CONST.read_text(encoding="utf-8")
        cls.lab = LAB.read_text(encoding="utf-8")
        cls.loader = LOADER.read_text(encoding="utf-8")

    def _candidates(self, public_id: str) -> set[str]:
        found = set()
        for provider_id, capabilities in self.runtime["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    found.add(f"{provider_id}/{capability_id}")
        return found

    def test_01_public_catalog_is_unchanged(self):
        self.assertGreaterEqual(len(self.runtime["public_capabilities"]), 226)
        self.assertEqual(set(PUBLIC), set(self.design["public_contracts"]))

    def test_02_each_species_has_exactly_one_candidate(self):
        for public_id, internal_id in PUBLIC.items():
            self.assertEqual(
                self._candidates(public_id),
                {f"open_meteo_pollen/{internal_id}"},
            )
            self.assertEqual(
                self.runtime["public_capabilities"][public_id]["strategy"],
                "single",
            )

    def test_03_resources_are_value_and_therefore_point_only(self):
        for public_id in PUBLIC:
            self.assertEqual(
                self.runtime["public_capabilities"][public_id]["resource_types"],
                ["value"],
            )
        self.assertEqual(self.design["context_contract"]["allowed"], ["point"])
        self.assertFalse(self.design["context_contract"]["global"])
        self.assertFalse(self.design["context_contract"]["bbox"])
        self.assertIn('if context["type"] != "point":', self.consumer)
        self.assertIn('"requirements_not_met"', self.consumer)

    def test_04_physical_semantics_are_pollen_concentration(self):
        p = self.runtime["capability_physical_semantics"]["providers"]["open_meteo_pollen"]
        for internal_id in PUBLIC.values():
            self.assertTrue(p[internal_id]["numeric"])
            self.assertEqual(p[internal_id]["quantity"], "pollen_concentration")
            self.assertEqual(p[internal_id]["unit_source"], "provider_capability")

    def test_05_source_and_observation_semantics_remain_forecast_model(self):
        source = self.runtime["capability_source_semantics"]["providers"]["open_meteo_pollen"]
        obs = self.runtime["capability_observation_semantics"]["providers"]["open_meteo_pollen"]
        for internal_id in PUBLIC.values():
            self.assertEqual(
                source[internal_id],
                {"data_origin": "model", "measurement_method": "pollen_forecast_model"},
            )
            self.assertEqual(obs[internal_id], {"observation_kind": "forecast"})

    def test_06_coverage_contract_matches_design(self):
        expected = self.design["coverage_target"]
        cov = self.runtime["capability_coverage_semantics"]["providers"]["open_meteo_pollen"]
        for internal_id in PUBLIC.values():
            item = cov[internal_id]
            for field in (
                "coverage_scope",
                "coverage_evidence",
                "routing_authority",
                "coordinate_space",
                "endpoint_reachability_is_coverage",
            ):
                self.assertEqual(item[field], expected[field])
            self.assertEqual(item["coverage_scope"], "regional")
            self.assertEqual(item["coverage_evidence"], "machine_readable_runtime")
            self.assertEqual(item["routing_authority"], "advisory")
            self.assertIs(item["endpoint_reachability_is_coverage"], False)

    def test_07_runtime_and_draft_maps_are_identical(self):
        self.assertEqual(self.runtime, self.draft)

    def test_08_provider_runtime_uses_cams_europe_and_explicit_coverage_status(self):
        self.assertIn('"domains": "cams_europe"', self.provider)
        self.assertIn('if response.status == 400:', self.provider)
        self.assertIn('"coverage_status": "outside_coverage"', self.provider)
        self.assertIn('"coverage_status": "inside_coverage"', self.provider)
        self.assertIn('response.raise_for_status()', self.provider)
        self.assertNotIn('async_get_coverage', self.provider)

    def test_09_endpoint_reachability_is_not_coverage(self):
        self.assertFalse(self.design["coverage_target"]["endpoint_reachability_is_coverage"])
        self.assertIn("endpoint reachability must never be coverage evidence", self.consumer)

    def test_10_no_medical_threshold_or_cross_species_contract(self):
        lowered = self.provider.lower()
        self.assertIn("keine personalisierte medizinische warnung", lowered)
        self.assertIn("universelle medizinische schwellenwerte werden nicht erfunden", lowered)
        self.assertFalse(self.design["medical_thresholds_added"])
        self.assertFalse(self.design["cross_species_fallback"])
        self.assertFalse(self.design["cross_species_aggregation"])

    def test_11_provider_remains_opt_in_pollen_domain(self):
        entry = next(item for item in self.registry["providers"] if item["module"] == "open_meteo_pollen")
        self.assertEqual(entry["domains"], ["pollen"])
        self.assertIs(entry["default_enabled"], False)

    def test_12_versions_are_exactly_synchronized(self):
        backend = re.search(r'DEV_BUILD_VERSION: Final = "([^"]+)"', self.const).group(1)
        loader_rev = re.search(r'DEV_LOADER_REV: Final = "([^"]+)"', self.const).group(1)
        lab = re.search(r'WR_LAB_BUILD_VERSION = "([^"]+)"', self.lab).group(1)
        loader_build = re.search(r'WR_LAB_BUILD_VERSION = "([^"]+)"', self.loader).group(1)
        loader = re.search(r'LOADER_REV = "([^"]+)"', self.loader).group(1)
        self.assertRegex(backend, r"^0\.10\.\d+$")
        self.assertRegex(loader_rev, r"^0\.10-loader-\d+$")
        self.assertEqual(backend, lab)
        self.assertEqual(backend, loader_build)
        self.assertEqual(loader_rev, loader)

if __name__ == "__main__":
    unittest.main()
