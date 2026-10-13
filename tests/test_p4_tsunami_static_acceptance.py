"""Independent static acceptance tests for P4-TSUNAMI-50."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p4_tsunami_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_MAP_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
HAZARD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
JMA_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "jma.py"
NOAA_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_tsunami.py"
BOM_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "bom_tsunami.py"
BMKG_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "bmkg_tsunami.py"
GDACS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "gdacs.py"
CONSUMER_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
DIAGNOSTIC_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
RESOLVE_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resolve.request.schema.json"
HAZARD_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resources" / "hazard_feed.schema.json"
CAPABILITIES_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "capabilities.response.schema.json"
RESPONSE_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resolve.response.schema.json"
DIAGNOSTIC_SCHEMA_PATH = ROOT / "contracts" / "diagnostics" / "routing_diagnostic.v1.schema.json"
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"
LAB_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab.js"
LOADER_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab-dev-loader.js"


def _load_hazard_common():
    spec = importlib.util.spec_from_file_location("weather_router_p4_tsunami_static_acceptance", HAZARD_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load hazard_common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _find_event_filter_options(node):
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict) and "event_filter_options" in props:
            return props["event_filter_options"]["properties"]
        for value in node.values():
            found = _find_event_filter_options(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_event_filter_options(value)
            if found is not None:
                return found
    return None


class P4TsunamiStaticAcceptanceTest(unittest.TestCase):
    """Independently verify P4-TSUNAMI runtime and contract boundaries."""

    @classmethod
    def setUpClass(cls):
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract_mapping = json.loads(CONTRACT_MAP_PATH.read_text(encoding="utf-8"))
        cls.hazard = _load_hazard_common()
        cls.jma = JMA_PATH.read_text(encoding="utf-8")
        cls.noaa = NOAA_PATH.read_text(encoding="utf-8")
        cls.bom = BOM_PATH.read_text(encoding="utf-8")
        cls.bmkg = BMKG_PATH.read_text(encoding="utf-8")
        cls.gdacs = GDACS_PATH.read_text(encoding="utf-8")
        cls.consumer = CONSUMER_PATH.read_text(encoding="utf-8")
        cls.diagnostic = DIAGNOSTIC_PATH.read_text(encoding="utf-8")
        cls.resolve_schema = json.loads(RESOLVE_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.hazard_schema = json.loads(HAZARD_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.capabilities_schema = json.loads(CAPABILITIES_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.response_schema = json.loads(RESPONSE_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.diagnostic_schema = json.loads(DIAGNOSTIC_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.const = CONST_PATH.read_text(encoding="utf-8")
        cls.lab = LAB_PATH.read_text(encoding="utf-8")
        cls.loader = LOADER_PATH.read_text(encoding="utf-8")

    def test_public_map_is_synchronized_and_count_stays_226(self):
        self.assertEqual(self.mapping, self.contract_mapping)
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        self.assertEqual(self.design["public_capabilities_added"], 0)

    def test_semantic_class_and_stage_contracts_match_design(self):
        self.assertEqual(
            set(self.design["event_semantics"]["semantic_classes"]),
            {
                "official_tsunami_warning_event",
                "tsunami_observation_event",
                "tsunami_potential_indicator_event",
                "disaster_awareness_tsunami_event",
            },
        )
        self.assertEqual(
            set(self.design["event_semantics"]["alert_stages"]),
            {
                "warning", "advisory", "watch", "threat", "marine_warning",
                "land_inundation_warning", "information", "no_threat", "canceled",
            },
        )

    def test_shared_helper_rejects_generic_only_stage(self):
        value = self.hazard.tsunami_semantics(
            "official_tsunami_warning_event",
            alert_stage="marine_warning",
            active_threat=True,
            wave_evidence="none",
        )
        self.assertEqual(value["alert_stage"], "marine_warning")
        with self.assertRaises(ValueError):
            self.hazard.tsunami_semantics(
                "official_tsunami_warning_event", alert_stage="outlook"
            )

    def test_provider_roles_are_not_collapsed(self):
        self.assertIn('"official_tsunami_warning_event"', self.jma)
        self.assertIn('"tsunami_observation_event"', self.jma)
        self.assertIn('"official_tsunami_warning_event"', self.noaa)
        self.assertIn('"official_tsunami_warning_event"', self.bom)
        self.assertIn('"tsunami_potential_indicator_event"', self.bmkg)
        self.assertIn('"disaster_awareness_tsunami_event"', self.gdacs)

    def test_jma_observation_and_bmkg_potential_map_are_correct(self):
        src = self.mapping["capability_source_semantics"]["providers"]
        obs = self.mapping["capability_observation_semantics"]["providers"]
        self.assertEqual(
            src["jma"]["tsunami_observations_japan"],
            {"data_origin": "warning_authority", "measurement_method": "tsunami_observation_feed"},
        )
        self.assertEqual(obs["jma"]["tsunami_observations_japan"]["observation_kind"], "observation")
        self.assertEqual(
            src["bmkg_tsunami"]["tsunami_potential_earthquake"],
            {"data_origin": "seismic_network", "measurement_method": "seismic_event_catalog"},
        )
        self.assertEqual(obs["bmkg_tsunami"]["tsunami_potential_earthquake"]["observation_kind"], "observation")

    def test_bmkg_epicenter_is_not_tsunami_impact_geometry(self):
        self.assertIn('"geometry": None', self.bmkg)
        self.assertIn('"earthquake_epicenter": geometry', self.bmkg)
        self.assertTrue(self.design["mappings"]["bmkg_potential"]["epicenter_is_tsunami_impact_area"] is False)

    def test_filter_capability_gates_match_design(self):
        self.assertIn("public_id not in _TSUNAMI_SEMANTIC_PUBLIC_IDS", self.consumer)
        self.assertIn("public_id not in _TSUNAMI_ALERT_STAGE_PUBLIC_IDS", self.consumer)
        semantic_ids = self.design["event_filter_additions"]["tsunami_semantic_classes"]["compatible_public_capabilities"]
        stage_ids = self.design["event_filter_additions"]["tsunami_alert_stages"]["compatible_public_capabilities"]
        for public_id in semantic_ids:
            self.assertIn(f'"{public_id}"', self.consumer)
        self.assertEqual(stage_ids, ["natural_hazards.tsunami.warnings"])

    def test_consumer_preserves_semantics_and_spatial_unknowns(self):
        for marker in (
            'raw_tsunami_semantics = raw.get("tsunami_semantics")',
            'event["tsunami_semantics"] = tsunami_meta',
            '"event_geometry_best_effort"',
            '"unknown_geometry"',
            '"matched_geometry"',
            '"geometry_nonmatched_count"',
            '"unknown_geometry_count"',
        ):
            self.assertIn(marker, self.consumer)

    def test_missing_geometry_is_not_outside_coverage(self):
        point_bbox = self.design["spatial_design"]["point_bbox"]
        self.assertFalse(point_bbox["missing_geometry_is_outside_coverage"])
        self.assertFalse(point_bbox["provider_identity_as_geometry"])
        self.assertFalse(point_bbox["region_text_as_geometry"])
        self.assertFalse(point_bbox["empty_explicit_geometry_matches_with_unknown_events_means_no_hazard"])

    def test_diagnostics_and_schemas_are_synchronized(self):
        for marker in (
            '"tsunami_semantic_classes"',
            '"tsunami_alert_stages"',
            '"tsunami_wave_evidence"',
            '"spatial_filter"',
        ):
            self.assertIn(marker, self.diagnostic)

        request_filters = self.resolve_schema["properties"]["event_filter"]["properties"]
        event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        resource_filters = self.hazard_schema["properties"]["event_filter"]["properties"]
        options = _find_event_filter_options(self.capabilities_schema)
        self.assertIsNotNone(options)
        for field in ("tsunami_semantic_classes", "tsunami_alert_stages"):
            self.assertIn(field, request_filters)
            self.assertIn(field, resource_filters)
            self.assertIn(field, options)
        self.assertIn("tsunami_semantics", event)
        self.assertIn("spatial_relevance", event)
        self.assertIn("spatial_filter", self.hazard_schema["properties"])
        self.assertIn(
            "tsunami_semantic_classes",
            self.response_schema["properties"]["resource"]["properties"]["payload"]["properties"],
        )
        self.assertIn(
            "tsunami_wave_evidence",
            self.diagnostic_schema["properties"]["resource"]["properties"],
        )

    def test_generic_alert_stage_contract_was_not_expanded(self):
        generic = self.resolve_schema["properties"]["event_filter"]["properties"]["alert_stages"]["items"]["enum"]
        self.assertEqual(set(generic), {"warning", "watch", "outlook", "statement", "unspecified"})
        for tsunami_only in ("advisory", "threat", "marine_warning", "land_inundation_warning", "no_threat", "canceled"):
            self.assertNotIn(tsunami_only, generic)

    def test_no_provider_priority_or_cross_provider_deduplication(self):
        runtime = (self.jma + self.noaa + self.bom + self.bmkg + self.gdacs + self.consumer).lower()
        for forbidden in ("preferred_provider", "provider_priority", "cross_provider_dedup"):
            self.assertNotIn(forbidden, runtime)

    def test_backend_lab_loader_are_synchronized(self):
        build = re.search(r'DEV_BUILD_VERSION: Final = "([^"]+)"', self.const)
        loader_rev = re.search(r'DEV_LOADER_REV: Final = "([^"]+)"', self.const)
        lab_build = re.search(r'WR_LAB_BUILD_VERSION = "([^"]+)"', self.lab)
        loader_build = re.search(r'WR_LAB_BUILD_VERSION = "([^"]+)"', self.loader)
        loader_frontend_rev = re.search(r'LOADER_REV = "([^"]+)"', self.loader)
        for match in (build, loader_rev, lab_build, loader_build, loader_frontend_rev):
            self.assertIsNotNone(match)
        self.assertEqual(build.group(1), lab_build.group(1))
        self.assertEqual(build.group(1), loader_build.group(1))
        self.assertEqual(loader_rev.group(1), loader_frontend_rev.group(1))
        self.assertGreaterEqual(int(build.group(1).rsplit(".", 1)[1]), 129)
        self.assertGreaterEqual(int(loader_rev.group(1).rsplit("-", 1)[1]), 132)


if __name__ == "__main__":
    unittest.main()
