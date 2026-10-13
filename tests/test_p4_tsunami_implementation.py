"""Runtime contract tests for P4-TSUNAMI-40 implementation."""
from __future__ import annotations
import importlib.util
import json
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
def read(path): return (ROOT / path).read_text(encoding="utf-8")
def load_hazard():
    path = ROOT / "custom_components/weather_router/providers/hazard_common.py"
    spec = importlib.util.spec_from_file_location("p4_tsunami_hazard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
def find_options(node):
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict) and "event_filter_options" in props:
            return props["event_filter_options"]["properties"]
        for value in node.values():
            found = find_options(value)
            if found is not None: return found
    elif isinstance(node, list):
        for value in node:
            found = find_options(value)
            if found is not None: return found
    return None

class P4TsunamiImplementationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = json.loads(read("docs/p4_tsunami_intent_design.v1.json"))
        cls.mapping = json.loads(read("custom_components/weather_router/consumer_capability_map.json"))
        cls.hazard = load_hazard()
        cls.jma = read("custom_components/weather_router/providers/jma.py")
        cls.noaa = read("custom_components/weather_router/providers/noaa_tsunami.py")
        cls.bom = read("custom_components/weather_router/providers/bom_tsunami.py")
        cls.bmkg = read("custom_components/weather_router/providers/bmkg_tsunami.py")
        cls.gdacs = read("custom_components/weather_router/providers/gdacs.py")
        cls.consumer = read("custom_components/weather_router/consumer_api.py")
        cls.diagnostic = read("custom_components/weather_router/routing_diagnostic_core.py")
        cls.request_schema = json.loads(read("contracts/consumer_v1/resolve.request.schema.json"))
        cls.hazard_schema = json.loads(read("contracts/consumer_v1/resources/hazard_feed.schema.json"))
        cls.cap_schema = json.loads(read("contracts/consumer_v1/capabilities.response.schema.json"))
        cls.response_schema = json.loads(read("contracts/consumer_v1/resolve.response.schema.json"))
        cls.diagnostic_schema = json.loads(read("contracts/diagnostics/routing_diagnostic.v1.schema.json"))
        cls.const = read("custom_components/weather_router/const.py")
        cls.lab = read("custom_components/weather_router/frontend/weather-router-lab.js")
        cls.loader = read("custom_components/weather_router/frontend/weather-router-lab-dev-loader.js")

    def test_no_new_public_capability(self):
        self.assertEqual(self.design["public_capabilities_added"], 0)
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)

    def test_shared_semantics_helper(self):
        value = self.hazard.tsunami_semantics(
            "official_tsunami_warning_event",
            alert_stage="advisory",
            active_threat=True,
            wave_evidence="expected",
        )
        self.assertEqual(value["alert_stage"], "advisory")
        self.assertTrue(value["active_threat"])
        with self.assertRaises(ValueError):
            self.hazard.tsunami_semantics(
                "official_tsunami_warning_event", alert_stage="outlook"
            )

    def test_provider_roles_and_revisions(self):
        for source in (self.jma, self.noaa, self.bom):
            self.assertIn('"official_tsunami_warning_event"', source)
        self.assertIn('"tsunami_observation_event"', self.jma)
        self.assertIn('"tsunami_potential_indicator_event"', self.bmkg)
        self.assertIn('"disaster_awareness_tsunami_event"', self.gdacs)
        self.assertIn('"geometry": None', self.bmkg)
        self.assertIn('"earthquake_epicenter": geometry', self.bmkg)
        for source in (self.jma, self.noaa, self.bom, self.bmkg):
            self.assertIn("wr-0.10.129-tsunami-semantics-1", source)
        self.assertRegex(
            self.gdacs,
            r'_PROVIDER_REVISION = "wr-0\.10\.\d+-[^"]*semantics-\d+"',
        )

    def test_capability_map_corrections(self):
        src = self.mapping["capability_source_semantics"]["providers"]
        obs = self.mapping["capability_observation_semantics"]["providers"]
        self.assertEqual(obs["jma"]["tsunami_observations_japan"]["observation_kind"], "observation")
        self.assertEqual(
            src["bmkg_tsunami"]["tsunami_potential_earthquake"],
            {"data_origin": "seismic_network", "measurement_method": "seismic_event_catalog"},
        )
        self.assertEqual(obs["bmkg_tsunami"]["tsunami_potential_earthquake"]["observation_kind"], "observation")

    def test_consumer_preservation_filters_and_spatial_contract(self):
        for marker in (
            "_TSUNAMI_SEMANTIC_PUBLIC_IDS",
            "_TSUNAMI_ALERT_STAGE_PUBLIC_IDS",
            '"tsunami_semantic_classes"',
            '"tsunami_alert_stages"',
            'raw_tsunami_semantics = raw.get("tsunami_semantics")',
            'event["tsunami_semantics"] = tsunami_meta',
            '"event_geometry_best_effort"',
            '"unknown_geometry"',
            '"matched_geometry"',
            '"geometry_nonmatched_count"',
        ):
            self.assertIn(marker, self.consumer)
        self.assertIn("public_id not in _TSUNAMI_SEMANTIC_PUBLIC_IDS", self.consumer)
        self.assertIn("public_id not in _TSUNAMI_ALERT_STAGE_PUBLIC_IDS", self.consumer)

    def test_diagnostics(self):
        for marker in (
            '"tsunami_semantic_classes"',
            '"tsunami_alert_stages"',
            '"tsunami_wave_evidence"',
            '"spatial_filter"',
        ):
            self.assertIn(marker, self.diagnostic)

    def test_schemas(self):
        request_filters = self.request_schema["properties"]["event_filter"]["properties"]
        event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        resource_filters = self.hazard_schema["properties"]["event_filter"]["properties"]
        options = find_options(self.cap_schema)
        for field in ("tsunami_semantic_classes", "tsunami_alert_stages"):
            self.assertIn(field, request_filters)
            self.assertIn(field, resource_filters)
            self.assertIn(field, options)
        self.assertIn("tsunami_semantics", event)
        self.assertIn("spatial_relevance", event)
        self.assertEqual(
            set(event["tsunami_semantics"]["properties"]["semantic_class"]["enum"]),
            set(self.design["event_semantics"]["semantic_classes"]),
        )
        self.assertIn("spatial_filter", self.hazard_schema["properties"])
        self.assertIn(
            "tsunami_semantic_classes",
            self.response_schema["properties"]["resource"]["properties"]["payload"]["properties"],
        )
        self.assertIn(
            "tsunami_wave_evidence",
            self.diagnostic_schema["properties"]["resource"]["properties"],
        )

    def test_generic_alert_stage_not_extended(self):
        generic = self.request_schema["properties"]["event_filter"]["properties"]["alert_stages"]["items"]["enum"]
        self.assertEqual(set(generic), {"warning", "watch", "outlook", "statement", "unspecified"})
        self.assertNotIn("advisory", generic)

    def test_versions_are_synchronized(self):
        backend = re.search(r'DEV_BUILD_VERSION: Final = "([^"]+)"', self.const).group(1)
        loader_rev = re.search(r'DEV_LOADER_REV: Final = "([^"]+)"', self.const).group(1)
        lab = re.search(r'WR_LAB_BUILD_VERSION = "([^"]+)"', self.lab).group(1)
        loader_build = re.search(r'WR_LAB_BUILD_VERSION = "([^"]+)"', self.loader).group(1)
        loader = re.search(r'LOADER_REV = "([^"]+)"', self.loader).group(1)
        self.assertGreaterEqual(int(backend.rsplit(".", 1)[1]), 129)
        self.assertGreaterEqual(int(loader_rev.rsplit("-", 1)[1]), 132)
        self.assertEqual(backend, lab)
        self.assertEqual(backend, loader_build)
        self.assertEqual(loader_rev, loader)

if __name__ == "__main__":
    unittest.main()
