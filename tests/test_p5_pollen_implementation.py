import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MAP = ROOT / "custom_components/weather_router/consumer_capability_map.json"
DRAFT_MAP = ROOT / "contracts/consumer_v1/capability-map.draft.json"
PROVIDER = ROOT / "custom_components/weather_router/providers/open_meteo_pollen.py"
CONST = ROOT / "custom_components/weather_router/const.py"
LAB = ROOT / "custom_components/weather_router/frontend/weather-router-lab.js"
LOADER = ROOT / "custom_components/weather_router/frontend/weather-router-lab-dev-loader.js"

PUBLIC = {
    "pollen.alder": "alder_pollen",
    "pollen.birch": "birch_pollen",
    "pollen.grass": "grass_pollen",
    "pollen.mugwort": "mugwort_pollen",
    "pollen.olive": "olive_pollen",
    "pollen.ragweed": "ragweed_pollen",
}

class P5PollenImplementationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = json.loads(RUNTIME_MAP.read_text(encoding="utf-8"))
        cls.draft = json.loads(DRAFT_MAP.read_text(encoding="utf-8"))
        cls.provider = PROVIDER.read_text(encoding="utf-8")
        cls.const = CONST.read_text(encoding="utf-8")
        cls.lab = LAB.read_text(encoding="utf-8")
        cls.loader = LOADER.read_text(encoding="utf-8")

    def test_public_count_and_contracts(self):
        self.assertGreaterEqual(len(self.runtime["public_capabilities"]), 226)
        provider_map = self.runtime["providers"]["open_meteo_pollen"]
        for public_id, internal_id in PUBLIC.items():
            self.assertIn(public_id, self.runtime["public_capabilities"])
            self.assertEqual(provider_map[internal_id], [public_id])
            meta = self.runtime["public_capabilities"][public_id]
            self.assertEqual(meta["strategy"], "single")
            self.assertEqual(meta["resource_types"], ["value"])

    def test_semantics_remain_forecast_concentration(self):
        for internal_id in PUBLIC.values():
            physical = self.runtime["capability_physical_semantics"]["providers"]["open_meteo_pollen"][internal_id]
            source = self.runtime["capability_source_semantics"]["providers"]["open_meteo_pollen"][internal_id]
            observation = self.runtime["capability_observation_semantics"]["providers"]["open_meteo_pollen"][internal_id]
            self.assertEqual(physical["quantity"], "pollen_concentration")
            self.assertTrue(physical["numeric"])
            self.assertEqual(source, {"data_origin": "model", "measurement_method": "pollen_forecast_model"})
            self.assertEqual(observation, {"observation_kind": "forecast"})

    def test_coverage_is_regional_runtime_and_advisory(self):
        expected = {
            "coverage_scope": "regional",
            "coverage_evidence": "machine_readable_runtime",
            "routing_authority": "advisory",
            "coordinate_space": "earth",
            "endpoint_reachability_is_coverage": False,
        }
        for internal_id in PUBLIC.values():
            self.assertEqual(
                self.runtime["capability_coverage_semantics"]["providers"]["open_meteo_pollen"][internal_id],
                expected,
            )
            self.assertEqual(
                self.draft["capability_coverage_semantics"]["providers"]["open_meteo_pollen"][internal_id],
                expected,
            )

    def test_runtime_and_draft_pollen_sections_match(self):
        sections = [
            "providers",
            "public_capabilities",
            "capability_resource_types",
            "capability_physical_semantics",
            "capability_source_semantics",
            "capability_observation_semantics",
            "capability_time_semantics",
            "capability_coverage_semantics",
        ]
        for section in sections:
            if section == "public_capabilities":
                for public_id in PUBLIC:
                    self.assertEqual(self.runtime[section][public_id], self.draft[section][public_id])
            else:
                r = self.runtime[section]
                d = self.draft[section]
                if "providers" in r:
                    r = r["providers"]
                    d = d["providers"]
                self.assertEqual(r["open_meteo_pollen"], d["open_meteo_pollen"])

    def test_provider_runtime_contract(self):
        self.assertIn('"domains": "cams_europe"', self.provider)
        self.assertIn('"coverage_status": "outside_coverage"', self.provider)
        self.assertIn('"coverage_status": "inside_coverage"', self.provider)
        self.assertIn('"Grains/m³"', self.provider)
        self.assertIn("async_fetch_point", self.provider)
        self.assertNotIn("async_get_map_layer", self.provider)
        self.assertNotIn("async_get_hazard_feed", self.provider)

    def test_no_medical_threshold_contract_added(self):
        lowered = self.provider.lower()
        self.assertIn("keine personalisierte medizinische warnung", lowered)
        self.assertIn("universelle medizinische schwellenwerte werden nicht erfunden", lowered)
        for token in ("allergy_risk", "pollen_severity", "medical_severity"):
            self.assertNotIn(token, lowered)

    def test_versions_are_synchronized(self):
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
