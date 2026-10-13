"""Independent static acceptance for P4-VOLCANO-50."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p4_volcano_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
DRAFT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
HAZARD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
GVP_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "smithsonian_volcanoes.py"
HANS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "usgs_volcanoes.py"
GDACS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "gdacs.py"
SEISMIC_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "usgs_seismic_events.py"
AVIATION_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "aviation_weather.py"
CONSUMER_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
DIAGNOSTIC_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
HAZARD_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resources" / "hazard_feed.schema.json"
DIAGNOSTIC_SCHEMA_PATH = ROOT / "contracts" / "diagnostics" / "routing_diagnostic.v1.schema.json"
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"
LAB_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab.js"
LOADER_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab-dev-loader.js"


def _load_hazard_common():
    spec = importlib.util.spec_from_file_location("weather_router_p4_volcano_static", HAZARD_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load hazard_common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P4VolcanoStaticAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
        cls.hazard = _load_hazard_common()
        cls.gvp = GVP_PATH.read_text(encoding="utf-8")
        cls.hans = HANS_PATH.read_text(encoding="utf-8")
        cls.gdacs = GDACS_PATH.read_text(encoding="utf-8")
        cls.seismic = SEISMIC_PATH.read_text(encoding="utf-8")
        cls.aviation = AVIATION_PATH.read_text(encoding="utf-8")
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

    def test_public_contracts_stay_single_and_separate(self):
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        self.assertEqual(
            self._candidates("natural_hazards.volcano.activity"),
            {"smithsonian_volcanoes/weekly_volcanic_activity"},
        )
        self.assertEqual(
            self._candidates("natural_hazards.volcano.warnings"),
            {"usgs_volcanoes/elevated_us_volcanoes"},
        )
        self.assertEqual(
            self.design["public_contracts"]["natural_hazards.volcano.activity"]["strategy"],
            "single",
        )
        self.assertEqual(
            self.design["public_contracts"]["natural_hazards.volcano.warnings"]["strategy"],
            "single",
        )
        self.assertTrue(self.design["no_shared_fallback"])

    def test_helper_accepts_exactly_the_four_approved_classes(self):
        approved = {
            "weekly_volcanic_activity_report_event",
            "official_volcano_status_event",
            "disaster_awareness_volcanic_event",
            "seismic_catalog_volcanic_event",
        }
        self.assertEqual(set(self.design["semantic_classes"]), approved)
        for semantic_class in approved:
            value = self.hazard.volcano_semantics(semantic_class)
            self.assertEqual(value["semantic_class"], semantic_class)
        with self.assertRaises(ValueError):
            self.hazard.volcano_semantics("confirmed_eruption_event")

    def test_gvp_is_weekly_report_role_only(self):
        self.assertIn('wr-0.10.132-gvp-http-identification-1', self.gvp)
        self.assertIn(
            '"User-Agent": "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev-pub)"',
            self.gvp,
        )
        self.assertIn('"weekly_volcanic_activity_report_event"', self.gvp)
        self.assertIn("report_type=kind", self.gvp)
        self.assertIn("report_categories=categories", self.gvp)
        self.assertNotIn('"official_volcano_status_event"', self.gvp)
        self.assertNotIn('"disaster_awareness_volcanic_event"', self.gvp)
        self.assertNotIn('"seismic_catalog_volcanic_event"', self.gvp)

    def test_hans_is_official_status_warning_and_warning_event(self):
        self.assertIn('wr-0.10.131-volcano-semantics-1', self.hans)
        self.assertIn('"official_volcano_status_event"', self.hans)
        obs = self.mapping["capability_observation_semantics"]["providers"][
            "usgs_volcanoes"
        ]["elevated_us_volcanoes"]
        self.assertEqual(obs["observation_kind"], "warning_event")
        self.assertIn('source_class="warning"', self.hans)

    def test_hans_preserves_aviation_and_alert_dimensions_separately(self):
        value = self.hazard.volcano_semantics(
            "official_volcano_status_event",
            aviation_color_code="ORANGE",
            volcano_alert_level="WATCH",
            nvews_threat="Very High",
        )
        self.assertEqual(value["aviation_color_code"], "ORANGE")
        self.assertEqual(value["volcano_alert_level"], "WATCH")
        self.assertEqual(value["nvews_threat"], "Very High")
        self.assertIn("aviation_color_code=color_code", self.hans)
        self.assertIn("volcano_alert_level=alert_level", self.hans)
        self.assertIn("legacy_severity_band=severity", self.hans)

    def test_gdacs_volcano_semantics_is_disaster_awareness_only(self):
        self.assertIn('wr-0.10.131-volcano-semantics-1', self.gdacs)
        self.assertIn('"disaster_awareness_volcanic_event"', self.gdacs)
        self.assertIn('if hazard_type == "volcanic_activity"', self.gdacs)
        self.assertIn('source_class="disaster_awareness"', self.gdacs)
        self.assertNotIn('"official_volcano_status_event"', self.gdacs)

    def test_usgs_non_earthquake_volcanic_stays_seismic_catalog(self):
        self.assertIn('wr-0.10.131-volcano-semantics-1', self.seismic)
        self.assertIn('"seismic_catalog_volcanic_event"', self.seismic)
        self.assertIn("source_event_type=event_type", self.seismic)
        self.assertIn('if hazard_type == "volcanic_activity"', self.seismic)
        self.assertIn("type != earthquake", self.seismic)
        self.assertNotIn('"official_volcano_status_event"', self.seismic)

    def test_aviation_volcanic_ash_stays_outside_volcano_semantics(self):
        self.assertIn('"va": "volcanic_ash"', self.aviation)
        self.assertIn('"volcanic ash": "volcanic_ash"', self.aviation)
        self.assertNotIn('"volcano_semantics"', self.aviation)

    def test_point_is_fail_closed_without_implicit_radius(self):
        self.assertIn("candidate.public_id in _VOLCANO_PUBLIC_IDS", self.consumer)
        self.assertIn('context["type"] == "point"', self.consumer)
        self.assertIn('"requirements_not_met"', self.consumer)
        self.assertIn("retryable=False", self.consumer)
        point = self.design["spatial"]["point"]
        self.assertEqual(point["action"], "reject_for_dedicated_volcano_public_ids")
        self.assertTrue(point["future_radius_contract_out_of_scope"])

    def test_bbox_diagnostic_is_event_point_filter_not_detection_claim(self):
        for marker in (
            '"volcano_event_point_bbox"',
            '"event_count_after_provider_filter"',
            '"point_geometry_count"',
            '"unknown_geometry_count"',
            '"complete": unknown_geometry_count == 0',
            '"detection_completeness_claim": False',
        ):
            self.assertIn(marker, self.consumer)
        self.assertEqual(
            self.design["spatial"]["bbox"]["mode"],
            "volcano_event_point_bbox",
        )
        self.assertFalse(
            self.design["spatial"]["bbox"]["detection_completeness_claim"]
        )

    def test_consumer_normalizes_only_approved_volcano_semantics(self):
        for marker in (
            "_VOLCANO_PUBLIC_IDS",
            "_VOLCANO_SEMANTIC_CLASSES",
            'raw_volcano_semantics = raw.get("volcano_semantics")',
            'event["volcano_semantics"] = volcano_meta',
            '"report_categories"',
        ):
            self.assertIn(marker, self.consumer)

    def test_routing_diagnostics_expose_all_volcano_dimensions(self):
        for field in self.design["diagnostics"]:
            self.assertIn(f'"{field}"', self.diagnostic)

    def test_consumer_diagnostic_schemas_and_draft_are_synchronized(self):
        event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        volcano = event["volcano_semantics"]
        self.assertEqual(volcano["required"], ["semantic_class"])
        self.assertEqual(
            set(volcano["properties"]["semantic_class"]["enum"]),
            set(self.design["semantic_classes"]),
        )
        modes = set(
            self.hazard_schema["properties"]["spatial_filter"]["properties"]["mode"]["enum"]
        )
        self.assertIn("volcano_event_point_bbox", modes)
        diagnostic = self.diagnostic_schema["properties"]["resource"]["properties"]
        for field in self.design["diagnostics"]:
            self.assertIn(field, diagnostic)

        runtime_obs = self.mapping["capability_observation_semantics"]["providers"]
        draft_obs = self.draft["capability_observation_semantics"]["providers"]
        self.assertEqual(
            runtime_obs["usgs_volcanoes"]["elevated_us_volcanoes"],
            draft_obs["usgs_volcanoes"]["elevated_us_volcanoes"],
        )
        self.assertEqual(
            runtime_obs["smithsonian_volcanoes"]["weekly_volcanic_activity"],
            draft_obs["smithsonian_volcanoes"]["weekly_volcanic_activity"],
        )
        self.assertEqual(
            draft_obs["usgs_volcanoes"]["elevated_us_volcanoes"]["observation_kind"],
            "warning_event",
        )

    def test_no_provider_priority_or_cross_feed_deduplication(self):
        self.assertFalse(self.design["provider_priority"])
        self.assertFalse(self.design["cross_provider_deduplication"])
        self.assertFalse(self.design["cross_feed_deduplication"])
        runtime = (
            self.gvp + self.hans + self.gdacs + self.seismic + self.consumer
        ).lower()
        for marker in (
            "preferred_provider",
            "provider_priority",
            "cross_provider_dedup",
            "cross_feed_dedup",
        ):
            self.assertNotIn(marker, runtime)

    def test_versions_are_exactly_synchronized(self):
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
