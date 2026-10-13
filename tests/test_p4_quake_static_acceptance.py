"""Independent static acceptance for P4-QUAKE-50."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p4_quake_intent_design.v1.json"
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
    spec = importlib.util.spec_from_file_location("weather_router_p4_quake_static", HAZARD_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load hazard_common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P4QuakeStaticAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
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

    def _candidates(self, public_id: str) -> set[str]:
        found: set[str] = set()
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    found.add(f"{provider_id}/{capability_id}")
        return found

    def test_public_contracts_and_count(self):
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        self.assertEqual(
            self._candidates("natural_hazards.earthquake.events"),
            {"usgs_earthquakes/earthquakes_past_day"},
        )
        self.assertEqual(
            self._candidates("natural_hazards.earthquake.significant_events"),
            {"usgs_earthquakes/significant_earthquakes_past_month"},
        )
        self.assertTrue(self.design["no_shared_fallback_between_earthquake_feeds"]["enabled"])

    def test_helper_accepts_only_approved_classes(self):
        for semantic_class in (
            "seismic_catalog_earthquake_event",
            "disaster_awareness_earthquake_event",
        ):
            result = self.hazard.earthquake_semantics(semantic_class)
            self.assertEqual(result["semantic_class"], semantic_class)
        with self.assertRaises(ValueError):
            self.hazard.earthquake_semantics("earthquake_warning")

    def test_usgs_catalog_selections_and_revision(self):
        self.assertIn("catalog_selection=(", self.usgs)
        self.assertIn('"significant_month"', self.usgs)
        self.assertIn('"all_day"', self.usgs)
        self.assertIn('capability_id == "significant_earthquakes_past_month"', self.usgs)
        self.assertIn('wr-0.10.130-quake-semantics-1', self.usgs)
        self.assertIn('"earthquake_semantics": quake_semantics', self.usgs)

    def test_usgs_preserves_measurement_dimensions(self):
        for marker in (
            "magnitude_type=props.get",
            "depth_km=depth_km",
            "community_intensity_cdi=props.get",
            "instrumental_intensity_mmi=props.get",
            "pager_alert=pager",
            "significance=props.get",
            "tsunami_flag=bool",
            "catalog_updated=updated",
        ):
            self.assertIn(marker, self.usgs)
        self.assertIn("weather_router_magnitude_display_band", self.usgs)

    def test_significant_semantics_remain_upstream(self):
        significant = self.design["public_contracts"][
            "natural_hazards.earthquake.significant_events"
        ]
        self.assertEqual(significant["role"], "upstream USGS significant-event selection")
        self.assertFalse(
            "magnitude threshold" in significant["role"].casefold()
        )

    def test_gdacs_role_is_disaster_awareness(self):
        self.assertIn('"disaster_awareness_earthquake_event"', self.gdacs)
        self.assertIn('"source_class": "disaster_awareness"', self.gdacs)
        self.assertFalse(self.design["provider_mapping"]["gdacs"]["primary_seismic_catalog"])

    def test_non_earthquake_and_bmkg_stay_separate(self):
        self.assertNotIn('"earthquake_semantics"', self.seismic)
        self.assertNotIn('"earthquake_semantics"', self.bmkg)
        self.assertIn('type != earthquake', self.seismic)
        self.assertIn('"hazard_type": "tsunami_potential"', self.bmkg)

    def test_point_is_fail_closed(self):
        self.assertIn('candidate.public_id in _EARTHQUAKE_PUBLIC_IDS', self.consumer)
        self.assertIn('context["type"] == "point"', self.consumer)
        self.assertIn('"requirements_not_met"', self.consumer)
        point = self.design["point_bbox_global"]["point"]
        self.assertEqual(point["action"], "reject_for_dedicated_earthquake_public_ids")
        self.assertTrue(point["future_radius_contract_out_of_scope"])

    def test_bbox_diagnostic_does_not_claim_network_completeness(self):
        for marker in (
            '"earthquake_event_point_bbox"',
            '"event_count_after_provider_filter"',
            '"point_geometry_count"',
            '"unknown_geometry_count"',
            '"detection_completeness_claim": False',
        ):
            self.assertIn(marker, self.consumer)

    def test_consumer_validates_typed_semantics(self):
        self.assertIn('raw_earthquake_semantics = raw.get("earthquake_semantics")', self.consumer)
        self.assertIn('event["earthquake_semantics"] = quake_meta', self.consumer)
        self.assertIn("_EARTHQUAKE_SEMANTIC_CLASSES", self.consumer)
        self.assertIn("_EARTHQUAKE_CATALOG_SELECTIONS", self.consumer)

    def test_routing_diagnostics_expose_all_quake_dimensions(self):
        for field in self.design["diagnostics"]["resource_summary_add"]:
            self.assertIn(f'"{field}"', self.diagnostic)

    def test_schemas_are_synchronized(self):
        event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        quake = event["earthquake_semantics"]
        self.assertEqual(quake["required"], ["semantic_class"])
        self.assertEqual(
            set(quake["properties"]["semantic_class"]["enum"]),
            {
                "seismic_catalog_earthquake_event",
                "disaster_awareness_earthquake_event",
            },
        )
        modes = set(
            self.hazard_schema["properties"]["spatial_filter"]["properties"]["mode"]["enum"]
        )
        self.assertTrue({"event_geometry_best_effort", "earthquake_event_point_bbox"}.issubset(modes))
        diagnostic = self.diagnostic_schema["properties"]["resource"]["properties"]
        for field in self.design["diagnostics"]["resource_summary_add"]:
            self.assertIn(field, diagnostic)

    def test_provider_priority_and_dedup_are_absent(self):
        runtime = (self.usgs + self.seismic + self.gdacs + self.bmkg + self.consumer).lower()
        for marker in (
            "preferred_provider",
            "provider_priority",
            "cross_provider_dedup",
            "cross_feed_dedup",
        ):
            self.assertNotIn(marker, runtime)

    def test_versions_are_synchronized(self):
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
