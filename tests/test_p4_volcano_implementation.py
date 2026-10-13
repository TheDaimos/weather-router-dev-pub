"""Runtime contract tests for P4-VOLCANO-40 implementation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
def read(path): return (ROOT / path).read_text(encoding="utf-8")

def load_hazard():
    path = ROOT / "custom_components/weather_router/providers/hazard_common.py"
    spec = importlib.util.spec_from_file_location("p4_volcano_hazard", path)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load hazard_common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class P4VolcanoImplementationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping = json.loads(read("custom_components/weather_router/consumer_capability_map.json"))
        cls.hazard = load_hazard()
        cls.gvp = read("custom_components/weather_router/providers/smithsonian_volcanoes.py")
        cls.hans = read("custom_components/weather_router/providers/usgs_volcanoes.py")
        cls.gdacs = read("custom_components/weather_router/providers/gdacs.py")
        cls.seismic = read("custom_components/weather_router/providers/usgs_seismic_events.py")
        cls.aviation = read("custom_components/weather_router/providers/aviation_weather.py")
        cls.consumer = read("custom_components/weather_router/consumer_api.py")
        cls.diagnostic = read("custom_components/weather_router/routing_diagnostic_core.py")
        cls.hazard_schema = json.loads(read("contracts/consumer_v1/resources/hazard_feed.schema.json"))
        cls.diagnostic_schema = json.loads(read("contracts/diagnostics/routing_diagnostic.v1.schema.json"))
        cls.const = read("custom_components/weather_router/const.py")
        cls.lab = read("custom_components/weather_router/frontend/weather-router-lab.js")
        cls.loader = read("custom_components/weather_router/frontend/weather-router-lab-dev-loader.js")

    def test_public_contracts_stay_separate(self):
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        self.assertEqual(self.mapping["providers"]["smithsonian_volcanoes"]["weekly_volcanic_activity"], ["natural_hazards.volcano.activity"])
        self.assertEqual(self.mapping["providers"]["usgs_volcanoes"]["elevated_us_volcanoes"], ["natural_hazards.volcano.warnings"])

    def test_helper_preserves_dimensions(self):
        value = self.hazard.volcano_semantics(
            "official_volcano_status_event",
            aviation_color_code="ORANGE",
            volcano_alert_level="WATCH",
            report_categories=["one", "", "one", "two"],
        )
        self.assertEqual(value["aviation_color_code"], "ORANGE")
        self.assertEqual(value["volcano_alert_level"], "WATCH")
        self.assertEqual(value["report_categories"], ["one", "two"])
        with self.assertRaises(ValueError):
            self.hazard.volcano_semantics("invalid")

    def test_provider_roles(self):
        self.assertIn('"weekly_volcanic_activity_report_event"', self.gvp)
        self.assertIn('"official_volcano_status_event"', self.hans)
        self.assertIn('"disaster_awareness_volcanic_event"', self.gdacs)
        self.assertIn('"seismic_catalog_volcanic_event"', self.seismic)
        self.assertIn("wr-0.10.132-gvp-http-identification-1", self.gvp)
        for source in (self.hans, self.gdacs, self.seismic):
            self.assertIn("wr-0.10.131-volcano-semantics-1", source)
        self.assertIn(
            '"User-Agent": "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev-pub)"',
            self.gvp,
        )
        self.assertNotIn('"volcano_semantics"', self.aviation)

    def test_hans_observation_kind(self):
        obs = self.mapping["capability_observation_semantics"]["providers"]["usgs_volcanoes"]["elevated_us_volcanoes"]
        self.assertEqual(obs["observation_kind"], "warning_event")
        self.assertIn("aviation_color_code=color_code", self.hans)
        self.assertIn("volcano_alert_level=alert_level", self.hans)

    def test_consumer_semantics_point_bbox(self):
        for marker in (
            "_VOLCANO_PUBLIC_IDS",
            "_VOLCANO_SEMANTIC_CLASSES",
            'raw_volcano_semantics = raw.get("volcano_semantics")',
            'event["volcano_semantics"] = volcano_meta',
            "Vulkan-Point-Abfragen benötigen",
            '"volcano_event_point_bbox"',
            '"detection_completeness_claim": False',
        ):
            self.assertIn(marker, self.consumer)

    def test_diagnostics(self):
        for marker in (
            '"volcano_semantic_classes"',
            '"volcano_report_types"',
            '"volcano_aviation_color_codes"',
            '"volcano_alert_levels"',
            '"volcano_source_event_types"',
        ):
            self.assertIn(marker, self.diagnostic)

    def test_schemas(self):
        event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        self.assertIn("volcano_semantics", event)
        self.assertEqual(event["volcano_semantics"]["required"], ["semantic_class"])
        modes = set(self.hazard_schema["properties"]["spatial_filter"]["properties"]["mode"]["enum"])
        self.assertTrue({"event_geometry_best_effort", "earthquake_event_point_bbox", "volcano_event_point_bbox"}.issubset(modes))
        props = self.diagnostic_schema["properties"]["resource"]["properties"]
        for field in (
            "volcano_semantic_classes",
            "volcano_report_types",
            "volcano_aviation_color_codes",
            "volcano_alert_levels",
            "volcano_source_event_types",
        ):
            self.assertIn(field, props)

    def test_versions(self):
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
