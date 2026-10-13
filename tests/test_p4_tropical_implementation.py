"""Runtime contract tests for P4-TROPICAL-40 implementation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p4_tropical_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
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
        "weather_router_p4_tropical_implementation",
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


class P4TropicalImplementationTest(unittest.TestCase):
    """Protect lifecycle semantics, source roles and Consumer V1 integration."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
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

    def test_no_new_public_capability(self) -> None:
        self.assertEqual(self.design["public_capabilities_added"], 0)
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        self.assertIn(
            "natural_hazards.tropical_cyclone.events",
            self.mapping["public_capabilities"],
        )

    def test_structured_classifier_preserves_lifecycle(self) -> None:
        cases = {
            "Potential Tropical Cyclone Six": "potential_tropical_cyclone",
            "Tropical Depression Seven": "tropical_depression",
            "Tropical Storm Alice": "tropical_storm",
            "Hurricane Bob": "hurricane_strength_tropical_cyclone",
            "Subtropical Storm Carol": "subtropical_cyclone",
            "Post-Tropical Cyclone Deb": "post_tropical_cyclone",
            "Remnant Low Erin": "post_tropical_cyclone",
            "Tropical Cyclone": "tropical_cyclone_unspecified",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                result = self.hazard.tropical_system_from_classification(raw)
                self.assertIsNotNone(result)
                self.assertEqual(result["system_class"], expected)
                self.assertEqual(result["source_classification"], raw)

    def test_nhc_currentstorms_classification_codes_are_normalized(self) -> None:
        cases = {
            "PC": ("potential_tropical_cyclone", None),
            "TD": ("tropical_depression", None),
            "TS": ("tropical_storm", None),
            "HU": ("hurricane_strength_tropical_cyclone", "hurricane"),
            "MH": ("hurricane_strength_tropical_cyclone", "hurricane"),
            "STD": ("subtropical_cyclone", None),
            "STS": ("subtropical_cyclone", None),
            "SD": ("subtropical_cyclone", None),
            "SS": ("subtropical_cyclone", None),
            "PTC": ("post_tropical_cyclone", None),
            "TY": ("hurricane_strength_tropical_cyclone", "typhoon"),
        }
        for raw, (expected_class, expected_term) in cases.items():
            with self.subTest(raw=raw):
                result = self.hazard.tropical_system_from_classification(raw)
                self.assertIsNotNone(result)
                self.assertEqual(result["system_class"], expected_class)
                self.assertEqual(result.get("regional_term"), expected_term)
                self.assertEqual(result["source_classification"], raw)

    def test_regional_terms_are_source_reported(self) -> None:
        hurricane = self.hazard.tropical_system_from_classification("Hurricane Alice")
        typhoon = self.hazard.tropical_system_from_classification("Typhoon Bob")
        severe = self.hazard.tropical_system_from_classification(
            "Severe Tropical Cyclone Carol"
        )
        self.assertEqual(hurricane["regional_term"], "hurricane")
        self.assertEqual(typhoon["regional_term"], "typhoon")
        self.assertEqual(severe["regional_term"], "severe_tropical_cyclone")

    def test_warning_product_name_is_not_current_system_classification(self) -> None:
        for event in (
            "Hurricane Warning",
            "Tropical Storm Watch",
            "Tropical Cyclone Advisory",
        ):
            with self.subTest(event=event):
                self.assertIsNone(
                    self.hazard.tropical_system_from_explicit_text(event, None)
                )

    def test_explicit_current_system_text_can_be_classified(self) -> None:
        result = self.hazard.tropical_system_from_explicit_text(
            "Tropical Storm Alice",
            "Tropical Storm Alice is active",
        )
        self.assertEqual(result["system_class"], "tropical_storm")
        self.assertEqual(result["classification_source"], "explicit_event_text")

    def test_nhc_uses_structured_classification_and_new_revision(self) -> None:
        self.assertIn("tropical_system_from_classification(", self.nhc)
        self.assertIn('classification_source="structured_provider_field"', self.nhc)
        self.assertIn('"tropical_system": tropical_system', self.nhc)
        self.assertIn(
            '_PROVIDER_REVISION = "wr-0.10.128-tropical-semantics-2"',
            self.nhc,
        )
        for marker in (
            '"classification": classification or None',
            '"intensity_kt": intensity',
            '"pressure_hpa": storm.get("pressure")',
            '"resources": resources',
        ):
            self.assertIn(marker, self.nhc)

    def test_general_warning_sources_use_explicit_text_only(self) -> None:
        for source in (self.dwd, self.nws):
            self.assertIn("tropical_system_from_explicit_text(", source)
            self.assertIn('event_payload["tropical_system"]', source)
        self.assertIn(
            '_DWD_PROVIDER_REVISION = "wr-0.10.127-tropical-semantics-1"',
            self.dwd,
        )

    def test_gdacs_and_aviation_are_unspecified_without_finer_evidence(self) -> None:
        self.assertIn('"system_class": "tropical_cyclone_unspecified"', self.gdacs)
        self.assertIn('"source_classification": "GDACS TC"', self.gdacs)
        self.assertIn('"system_class": "tropical_cyclone_unspecified"', self.aviation)
        self.assertIn('"source_classification": hazard', self.aviation)
        self.assertRegex(
            self.gdacs,
            r'_PROVIDER_REVISION = "wr-0\.10\.\d+-[^"]*semantics-\d+"',
        )
        self.assertIn(
            '_PROVIDER_REVISION = "wr-0.10.127-tropical-semantics-1"',
            self.aviation,
        )

    def test_consumer_preserves_and_validates_tropical_system(self) -> None:
        for marker in (
            "_TROPICAL_SYSTEM_PUBLIC_IDS",
            "_TROPICAL_SYSTEM_CLASSES",
            'raw_tropical_system = raw.get("tropical_system")',
            'event["tropical_system"] = tropical_system',
            '"tropical_system_classes"',
        ):
            self.assertIn(marker, self.consumer)

    def test_tropical_filter_is_explicitly_capability_gated(self) -> None:
        self.assertIn("public_id not in _TROPICAL_SYSTEM_PUBLIC_IDS", self.consumer)
        for public_id in self.design["event_filter_additions"][
            "compatible_public_capabilities"
        ]:
            self.assertIn(f'"{public_id}"', self.consumer)

    def test_diagnostics_expose_tropical_dimensions(self) -> None:
        self.assertIn('"tropical_system_classes"', self.diagnostic)
        self.assertIn('"tropical_regional_terms"', self.diagnostic)

    def test_consumer_v1_schemas_are_synchronized(self) -> None:
        request_filters = self.resolve_schema["properties"]["event_filter"]["properties"]
        hazard_event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        hazard_filters = self.hazard_schema["properties"]["event_filter"]["properties"]
        capability_options = _find_event_filter_options(self.capabilities_schema)
        self.assertIsNotNone(capability_options)

        self.assertIn("tropical_system_classes", request_filters)
        self.assertIn("tropical_system_classes", hazard_filters)
        self.assertIn("tropical_system_classes", capability_options)
        self.assertIn("tropical_system", hazard_event)

        tropical = hazard_event["tropical_system"]
        self.assertEqual(tropical["required"], ["system_class"])
        self.assertEqual(
            set(tropical["properties"]["system_class"]["enum"]),
            set(self.design["event_semantics"]["system_classes"]),
        )

    def test_track_cone_and_surge_resources_remain_parameters(self) -> None:
        self.assertIn('"resources": resources', self.nhc)
        self.assertNotIn('"hazard_type": "storm_surge"', self.nhc)
        self.assertFalse(self.design["forecast_resources"]["new_public_capability"])
        self.assertFalse(self.design["forecast_resources"]["new_resource_type"])

    def test_provider_priority_and_cross_provider_dedup_are_not_introduced(self) -> None:
        runtime = (
            self.nhc + self.dwd + self.nws + self.gdacs + self.aviation + self.consumer
        ).lower()
        self.assertNotIn("preferred_provider", runtime)
        self.assertNotIn("provider_priority", runtime)
        self.assertNotIn("cross_provider_dedup", runtime)

    def test_backend_frontend_and_loader_are_version_synchronized(self) -> None:
        backend = re.search(r'DEV_BUILD_VERSION: Final = "([^"]+)"', self.const)
        loader_rev = re.search(r'DEV_LOADER_REV: Final = "([^"]+)"', self.const)
        lab = re.search(r'WR_LAB_BUILD_VERSION = "([^"]+)"', self.lab)
        loader_build = re.search(r'WR_LAB_BUILD_VERSION = "([^"]+)"', self.loader)
        loader = re.search(r'LOADER_REV = "([^"]+)"', self.loader)
        self.assertIsNotNone(backend)
        self.assertIsNotNone(loader_rev)
        self.assertIsNotNone(lab)
        self.assertIsNotNone(loader_build)
        self.assertIsNotNone(loader)
        self.assertGreaterEqual(int(backend.group(1).rsplit(".", 1)[1]), 128)
        self.assertGreaterEqual(int(loader_rev.group(1).rsplit("-", 1)[1]), 131)
        self.assertEqual(backend.group(1), lab.group(1))
        self.assertEqual(backend.group(1), loader_build.group(1))
        self.assertEqual(loader_rev.group(1), loader.group(1))


if __name__ == "__main__":
    unittest.main()
