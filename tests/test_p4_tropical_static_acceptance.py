"""Independent static acceptance tests for P4-TROPICAL-50."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p4_tropical_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_MAP_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
HAZARD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
NHC_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "nhc_tropical_cyclones.py"
DWD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "dwd.py"
NWS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_nws.py"
GDACS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "gdacs.py"
AVIATION_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "aviation_weather.py"
CONSUMER_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
DIAGNOSTIC_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
RESOLVE_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resolve.request.schema.json"
HAZARD_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resources" / "hazard_feed.schema.json"
CAPABILITIES_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "capabilities.response.schema.json"
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"
LAB_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab.js"
LOADER_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab-dev-loader.js"


def _load_hazard_common():
    spec = importlib.util.spec_from_file_location(
        "weather_router_p4_tropical_static_acceptance",
        HAZARD_PATH,
    )
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


class P4TropicalStaticAcceptanceTest(unittest.TestCase):
    """Independently verify P4-TROPICAL runtime and contract boundaries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract_mapping = json.loads(CONTRACT_MAP_PATH.read_text(encoding="utf-8"))
        cls.hazard = _load_hazard_common()
        cls.nhc = NHC_PATH.read_text(encoding="utf-8")
        cls.dwd = DWD_PATH.read_text(encoding="utf-8")
        cls.nws = NWS_PATH.read_text(encoding="utf-8")
        cls.gdacs = GDACS_PATH.read_text(encoding="utf-8")
        cls.aviation = AVIATION_PATH.read_text(encoding="utf-8")
        cls.consumer = CONSUMER_PATH.read_text(encoding="utf-8")
        cls.diagnostic = DIAGNOSTIC_PATH.read_text(encoding="utf-8")
        cls.resolve_schema = json.loads(RESOLVE_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.hazard_schema = json.loads(HAZARD_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.capabilities_schema = json.loads(
            CAPABILITIES_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        cls.const = CONST_PATH.read_text(encoding="utf-8")
        cls.lab = LAB_PATH.read_text(encoding="utf-8")
        cls.loader = LOADER_PATH.read_text(encoding="utf-8")

    def test_public_map_is_synchronized_and_no_new_public_id_exists(self) -> None:
        self.assertEqual(self.mapping, self.contract_mapping)
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        self.assertEqual(self.design["public_capabilities_added"], 0)

    def test_dedicated_tropical_transport_is_still_nhc_only(self) -> None:
        target = "natural_hazards.tropical_cyclone.events"
        actual = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if target in public_ids:
                    actual.append(f"{provider_id}/{capability_id}")
        self.assertEqual(actual, ["nhc_tropical_cyclones/active_tropical_cyclones"])

    def test_lifecycle_classes_match_design_exactly(self) -> None:
        expected = [
            "potential_tropical_cyclone",
            "tropical_depression",
            "tropical_storm",
            "hurricane_strength_tropical_cyclone",
            "subtropical_cyclone",
            "post_tropical_cyclone",
            "tropical_cyclone_unspecified",
        ]
        self.assertEqual(self.design["event_semantics"]["system_classes"], expected)

    def test_potential_and_post_tropical_are_not_collapsed(self) -> None:
        potential = self.hazard.tropical_system_from_classification(
            "Potential Tropical Cyclone Nine"
        )
        post = self.hazard.tropical_system_from_classification(
            "Post-Tropical Cyclone Alice"
        )
        self.assertEqual(potential["system_class"], "potential_tropical_cyclone")
        self.assertEqual(post["system_class"], "post_tropical_cyclone")

    def test_nhc_currentstorms_codes_preserve_lifecycle(self) -> None:
        cases = {
            "PC": "potential_tropical_cyclone",
            "TD": "tropical_depression",
            "TS": "tropical_storm",
            "HU": "hurricane_strength_tropical_cyclone",
            "STD": "subtropical_cyclone",
            "STS": "subtropical_cyclone",
            "PTC": "post_tropical_cyclone",
            "TY": "hurricane_strength_tropical_cyclone",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                result = self.hazard.tropical_system_from_classification(raw)
                self.assertIsNotNone(result)
                self.assertEqual(result["system_class"], expected)

    def test_confirmed_tropical_stages_are_distinct(self) -> None:
        cases = {
            "Tropical Depression One": "tropical_depression",
            "Tropical Storm Two": "tropical_storm",
            "Hurricane Three": "hurricane_strength_tropical_cyclone",
            "Subtropical Storm Four": "subtropical_cyclone",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(
                    self.hazard.tropical_system_from_classification(value)["system_class"],
                    expected,
                )

    def test_regional_terms_are_not_provider_id_inference(self) -> None:
        self.assertEqual(
            self.hazard.tropical_system_from_classification("Hurricane Alice")[
                "regional_term"
            ],
            "hurricane",
        )
        self.assertEqual(
            self.hazard.tropical_system_from_classification("Typhoon Bob")[
                "regional_term"
            ],
            "typhoon",
        )
        regional = self.design["regional_term"]
        self.assertFalse(regional["derive_from_provider_id"])
        self.assertFalse(regional["derive_from_geography"])

    def test_warning_products_do_not_become_current_system_class(self) -> None:
        for value in (
            "Hurricane Warning",
            "Tropical Storm Watch",
            "Tropical Cyclone Advisory",
            "Hurricane Forecast",
        ):
            with self.subTest(value=value):
                self.assertIsNone(
                    self.hazard.tropical_system_from_explicit_text(value, None)
                )

    def test_context_only_forecast_text_is_not_used_for_current_lifecycle(self) -> None:
        self.assertTrue(
            self.design["general_weather_warning_design"][
                "attach_from_explicit_event_or_headline_only"
            ]
        )
        self.assertFalse(
            self.design["general_weather_warning_design"][
                "description_or_instruction_only"
            ]
        )
        for source in (self.dwd, self.nws):
            self.assertIn(
                "tropical_system_from_explicit_text(",
                source,
            )

    def test_nhc_preserves_structured_source_and_resources(self) -> None:
        self.assertIn('classification_source="structured_provider_field"', self.nhc)
        self.assertIn('"tropical_system": tropical_system', self.nhc)
        self.assertRegex(
            self.nhc,
            r'_PROVIDER_REVISION = "wr-0\.10\.\d+-[^"]*semantics-\d+"',
        )
        for marker in (
            '"classification": classification or None',
            '"intensity_kt": intensity',
            '"pressure_hpa": storm.get("pressure")',
            '"forecast_track"',
            '"track_cone"',
            '"forecast_wind_radii"',
            '"wind_speed_probabilities"',
            '"storm_surge_watch_warning"',
        ):
            self.assertIn(marker, self.nhc)

    def test_gdacs_and_aviation_keep_source_roles(self) -> None:
        self.assertIn('"system_class": "tropical_cyclone_unspecified"', self.gdacs)
        self.assertIn('"source_class": "disaster_awareness"', self.gdacs)
        self.assertIn('"system_class": "tropical_cyclone_unspecified"', self.aviation)
        self.assertIn('"official_aviation_warning"', self.aviation)
        self.assertTrue(
            self.design["gdacs_design"]["preserve_disaster_awareness_role"]
        )
        self.assertFalse(
            self.design["gdacs_design"]["infer_finer_intensity"]
        )
        self.assertTrue(
            self.design["aviation_design"]["preserve_aviation_role"]
        )
        self.assertFalse(
            self.design["aviation_design"]["infer_finer_intensity"]
        )

    def test_storm_surge_is_not_auto_promoted(self) -> None:
        self.assertFalse(
            self.design["storm_surge"]["auto_event_from_nhc_resource_link"]
        )
        self.assertNotIn('"hazard_type": "storm_surge"', self.nhc)

    def test_consumer_filter_gate_matches_design_exactly(self) -> None:
        self.assertIn("_TROPICAL_SYSTEM_PUBLIC_IDS", self.consumer)
        self.assertIn("public_id not in _TROPICAL_SYSTEM_PUBLIC_IDS", self.consumer)
        for public_id in self.design["event_filter_additions"][
            "compatible_public_capabilities"
        ]:
            self.assertIn(f'"{public_id}"', self.consumer)

    def test_consumer_preserves_only_known_tropical_semantics(self) -> None:
        for marker in (
            'raw_tropical_system = raw.get("tropical_system")',
            "system_class in _TROPICAL_SYSTEM_CLASSES",
            "regional_term in _TROPICAL_REGIONAL_TERMS",
            "classification_source in _TROPICAL_CLASSIFICATION_SOURCES",
            'event["tropical_system"] = tropical_system',
        ):
            self.assertIn(marker, self.consumer)

    def test_filter_matches_nested_system_class(self) -> None:
        for marker in (
            'requested_tropical_classes = event_filter.get("tropical_system_classes")',
            'tropical_system = event.get("tropical_system")',
            'tropical_system.get("system_class")',
        ):
            self.assertIn(marker, self.consumer)

    def test_diagnostics_and_schemas_are_synchronized(self) -> None:
        self.assertIn('"tropical_system_classes"', self.diagnostic)
        self.assertIn('"tropical_regional_terms"', self.diagnostic)

        request_filters = self.resolve_schema["properties"]["event_filter"]["properties"]
        hazard_event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        hazard_filters = self.hazard_schema["properties"]["event_filter"]["properties"]
        capability_options = _find_event_filter_options(self.capabilities_schema)
        self.assertIsNotNone(capability_options)

        self.assertIn("tropical_system_classes", request_filters)
        self.assertIn("tropical_system_classes", hazard_filters)
        self.assertIn("tropical_system_classes", capability_options)
        self.assertIn("tropical_system", hazard_event)

    def test_existing_flood_semantics_remain_present(self) -> None:
        for source in (self.dwd, self.nws):
            self.assertIn("flood_semantics(", source)
            self.assertIn('"flood_semantics"', source)
        self.assertIn("_FLOOD_SEMANTIC_PUBLIC_IDS", self.consumer)
        self.assertIn('"flood_semantic_classes"', self.diagnostic)

    def test_no_provider_priority_or_cross_provider_deduplication(self) -> None:
        runtime = (
            self.nhc + self.dwd + self.nws + self.gdacs + self.aviation + self.consumer
        ).lower()
        for forbidden in ("preferred_provider", "provider_priority", "cross_provider_dedup"):
            self.assertNotIn(forbidden, runtime)

    def test_backend_lab_loader_are_synchronized(self) -> None:
        build = re.search(r'DEV_BUILD_VERSION: Final = "([^"]+)"', self.const)
        loader_rev = re.search(r'DEV_LOADER_REV: Final = "([^"]+)"', self.const)
        lab_build = re.search(r'WR_LAB_BUILD_VERSION = "([^"]+)"', self.lab)
        loader_build = re.search(r'WR_LAB_BUILD_VERSION = "([^"]+)"', self.loader)
        loader_frontend_rev = re.search(r'LOADER_REV = "([^"]+)"', self.loader)
        for match in (build, loader_rev, lab_build, loader_build, loader_frontend_rev):
            self.assertIsNotNone(match)
        self.assertGreaterEqual(int(build.group(1).rsplit(".", 1)[1]), 128)
        self.assertGreaterEqual(int(loader_rev.group(1).rsplit("-", 1)[1]), 131)
        self.assertEqual(build.group(1), lab_build.group(1))
        self.assertEqual(build.group(1), loader_build.group(1))
        self.assertEqual(loader_rev.group(1), loader_frontend_rev.group(1))


if __name__ == "__main__":
    unittest.main()
