"""Runtime contract tests for P4-QUAKE-40 implementation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
HAZARD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
USGS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "usgs_earthquakes.py"
SEISMIC_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "usgs_seismic_events.py"
GDACS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "gdacs.py"
BMKG_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "bmkg_tsunami.py"
CONSUMER_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
DIAGNOSTIC_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
HAZARD_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resources" / "hazard_feed.schema.json"
DIAGNOSTIC_SCHEMA_PATH = ROOT / "contracts" / "diagnostics" / "routing_diagnostic.v1.schema.json"
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"
LAB_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab.js"
LOADER_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab-dev-loader.js"


def _load_hazard_common():
    spec = importlib.util.spec_from_file_location("weather_router_p4_quake_impl", HAZARD_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load hazard_common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P4QuakeImplementationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.hazard = _load_hazard_common()
        cls.usgs = USGS_PATH.read_text(encoding="utf-8")
        cls.seismic = SEISMIC_PATH.read_text(encoding="utf-8")
        cls.gdacs = GDACS_PATH.read_text(encoding="utf-8")
        cls.bmkg = BMKG_PATH.read_text(encoding="utf-8")
        cls.consumer = CONSUMER_PATH.read_text(encoding="utf-8")
        cls.diagnostic = DIAGNOSTIC_PATH.read_text(encoding="utf-8")
        cls.hazard_schema = json.loads(HAZARD_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.diagnostic_schema = json.loads(DIAGNOSTIC_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.const = CONST_PATH.read_text(encoding="utf-8")
        cls.lab = LAB_PATH.read_text(encoding="utf-8")
        cls.loader = LOADER_PATH.read_text(encoding="utf-8")

    def test_public_capability_count_unchanged(self):
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)

    def test_helper(self):
        value = self.hazard.earthquake_semantics(
            "seismic_catalog_earthquake_event",
            catalog_selection="all_day",
            magnitude=5.2,
            tsunami_flag=False,
        )
        self.assertEqual(value["catalog_selection"], "all_day")
        self.assertEqual(value["magnitude"], 5.2)
        with self.assertRaises(ValueError):
            self.hazard.earthquake_semantics("invalid")
        with self.assertRaises(ValueError):
            self.hazard.earthquake_semantics(
                "seismic_catalog_earthquake_event", catalog_selection="weekly"
            )

    def test_usgs(self):
        self.assertIn('"seismic_catalog_earthquake_event"', self.usgs)
        self.assertIn('"significant_month"', self.usgs)
        self.assertIn('"all_day"', self.usgs)
        self.assertIn('wr-0.10.130-quake-semantics-1', self.usgs)
        self.assertIn('"earthquake_semantics": quake_semantics', self.usgs)

    def test_gdacs_role(self):
        self.assertIn('"disaster_awareness_earthquake_event"', self.gdacs)
        self.assertIn('if hazard_type == "earthquake"', self.gdacs)
        self.assertRegex(
            self.gdacs,
            r'_PROVIDER_REVISION = "wr-0\.10\.\d+-[^\"]*semantics-\d+"',
        )
        self.assertIn('"source_class": "disaster_awareness"', self.gdacs)

    def test_related_paths_not_promoted(self):
        self.assertNotIn('"earthquake_semantics"', self.seismic)
        self.assertNotIn('"earthquake_semantics"', self.bmkg)
        self.assertIn('"hazard_type": "tsunami_potential"', self.bmkg)

    def test_consumer_preservation_and_point_gate(self):
        for marker in (
            "_EARTHQUAKE_PUBLIC_IDS",
            "_EARTHQUAKE_SEMANTIC_CLASSES",
            'raw_earthquake_semantics = raw.get("earthquake_semantics")',
            'event["earthquake_semantics"] = quake_meta',
            '"requirements_not_met"',
            '"earthquake_event_point_bbox"',
            '"detection_completeness_claim": False',
        ):
            self.assertIn(marker, self.consumer)

    def test_diagnostics(self):
        for marker in (
            '"earthquake_semantic_classes"',
            '"earthquake_catalog_selections"',
            '"earthquake_magnitude_types"',
            '"earthquake_pager_alerts"',
            '"earthquake_tsunami_flag_count"',
            '"earthquake_magnitude_range"',
            '"earthquake_depth_km_range"',
        ):
            self.assertIn(marker, self.diagnostic)

    def test_schemas(self):
        event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        self.assertIn("earthquake_semantics", event)
        self.assertEqual(event["earthquake_semantics"]["required"], ["semantic_class"])
        modes = set(
            self.hazard_schema["properties"]["spatial_filter"]["properties"]["mode"]["enum"]
        )
        self.assertTrue(
            {"event_geometry_best_effort", "earthquake_event_point_bbox"}.issubset(modes)
        )
        props = self.diagnostic_schema["properties"]["resource"]["properties"]
        for field in (
            "earthquake_semantic_classes",
            "earthquake_catalog_selections",
            "earthquake_magnitude_types",
            "earthquake_pager_alerts",
            "earthquake_tsunami_flag_count",
            "earthquake_magnitude_range",
            "earthquake_depth_km_range",
        ):
            self.assertIn(field, props)

    def test_versions(self):
        backend = re.search(r'DEV_BUILD_VERSION: Final = "([^"]+)"', self.const).group(1)
        loader_rev = re.search(r'DEV_LOADER_REV: Final = "([^"]+)"', self.const).group(1)
        lab = re.search(r'WR_LAB_BUILD_VERSION = "([^"]+)"', self.lab).group(1)
        loader_build = re.search(r'WR_LAB_BUILD_VERSION = "([^"]+)"', self.loader).group(1)
        loader = re.search(r'LOADER_REV = "([^"]+)"', self.loader).group(1)
        self.assertGreaterEqual(int(backend.rsplit(".", 1)[1]), 130)
        self.assertGreaterEqual(int(loader_rev.rsplit("-", 1)[1]), 133)
        self.assertEqual(backend, lab)
        self.assertEqual(backend, loader_build)
        self.assertEqual(loader_rev, loader)


if __name__ == "__main__":
    unittest.main()
