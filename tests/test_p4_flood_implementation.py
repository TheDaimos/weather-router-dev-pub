"""Runtime contract tests for P4-FLOOD-40 implementation."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p4_flood_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
HAZARD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
BBK_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "bbk_warning_common.py"
DWD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "dwd.py"
NWS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_nws.py"
NINA_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "nina_supplementary.py"
GLOFAS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "glofas.py"
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
        "weather_router_p4_flood_implementation",
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


class P4FloodImplementationTest(unittest.TestCase):
    """Protect the approved multi-valued flood semantics and routing boundaries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.hazard = _load_hazard_common()
        cls.hazard_source = HAZARD_PATH.read_text(encoding="utf-8")
        cls.bbk = BBK_PATH.read_text(encoding="utf-8")
        cls.dwd = DWD_PATH.read_text(encoding="utf-8")
        cls.nws = NWS_PATH.read_text(encoding="utf-8")
        cls.nina = NINA_PATH.read_text(encoding="utf-8")
        cls.glofas = GLOFAS_PATH.read_text(encoding="utf-8")
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

    def test_no_new_public_capability_and_transports_remain_distinct(self) -> None:
        self.assertEqual(self.design["public_capabilities_added"], 0)
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        self.assertIn("weather.warning.official", self.mapping["public_capabilities"])
        self.assertIn("natural_hazards.flood.warning", self.mapping["public_capabilities"])
        self.assertIn("civil_protection.warning.official", self.mapping["public_capabilities"])

    def test_flash_flood_does_not_create_generic_flood_by_substring_alone(self) -> None:
        self.assertEqual(
            self.hazard.flood_semantics(event="Flash Flood Warning"),
            [
                {
                    "semantic_class": "official_flash_flood_alert_event",
                    "match_scope": "explicit_event",
                }
            ],
        )

    def test_generic_and_specific_flood_can_coexist_with_independent_evidence(self) -> None:
        result = self.hazard.flood_semantics(
            event="Flood Warning",
            description="A flash flood and debris flow may develop.",
        )
        self.assertEqual(
            result,
            [
                {
                    "semantic_class": "official_flood_alert_event",
                    "match_scope": "explicit_event",
                },
                {
                    "semantic_class": "official_debris_flow_alert_event",
                    "match_scope": "contextual_text",
                },
                {
                    "semantic_class": "official_flash_flood_alert_event",
                    "match_scope": "contextual_text",
                },
            ],
        )

    def test_multiple_specific_flood_classes_can_coexist(self) -> None:
        result = self.hazard.flood_semantics(
            headline="Dam failure with flash flood and debris flow risk"
        )
        classes = [item["semantic_class"] for item in result]
        self.assertEqual(
            classes,
            [
                "official_dam_failure_alert_event",
                "official_debris_flow_alert_event",
                "official_flash_flood_alert_event",
            ],
        )
        self.assertTrue(all(item["match_scope"] == "explicit_event" for item in result))

    def test_explicit_scope_wins_for_the_same_semantic_class(self) -> None:
        result = self.hazard.flood_semantics(
            headline="Flash Flood Warning",
            description="Flash flood expected in low-lying areas.",
        )
        self.assertEqual(
            result,
            [
                {
                    "semantic_class": "official_flash_flood_alert_event",
                    "match_scope": "explicit_event",
                }
            ],
        )

    def test_heavy_rain_and_coastal_flood_do_not_promote_to_p4_flood_semantics(self) -> None:
        self.assertEqual(
            self.hazard.flood_semantics(event="Heavy Rain Warning"),
            [],
        )
        self.assertEqual(
            self.hazard.flood_semantics(event="Coastal Flood Warning"),
            [],
        )

    def test_glof_and_ice_jam_are_real_title_reachable_in_nina_classifier(self) -> None:
        for marker in (
            '"glacial_lake_outburst_flood"',
            '"ice_jam_flood"',
            '"glof"',
            '"gletscherseeausbruch"',
            '"ice jam flood"',
            '"eisstau"',
        ):
            self.assertIn(marker, self.bbk)

    def test_dwd_and_nws_attach_multi_valued_flood_semantics(self) -> None:
        for source in (self.dwd, self.nws):
            self.assertIn("flood_semantics(", source)
            self.assertIn('"flood_semantics"', source)
        self.assertIn('event_payload.setdefault("alert_stage", "warning")', self.dwd)
        self.assertIn("normalize_alert_stage(event_name, headline)", self.nws)

    def test_nina_uses_real_headline_only_for_flood_semantics(self) -> None:
        self.assertIn("semantics = flood_semantics(headline=event.get(\"headline\"))", self.nina)
        self.assertIn('event["flood_semantics"] = semantics', self.nina)
        self.assertNotIn("flood_semantics(event=self.event_label", self.nina)

    def test_flood_filters_are_limited_to_approved_warning_capabilities(self) -> None:
        self.assertIn("_FLOOD_SEMANTIC_PUBLIC_IDS", self.consumer)
        for public_id in (
            "weather.warning.official",
            "natural_hazards.flood.warning",
            "civil_protection.warning.official",
        ):
            self.assertIn(f'"{public_id}"', self.consumer)
        self.assertIn('"flood_semantic_classes"', self.consumer)
        self.assertIn('"flood_match_scopes"', self.consumer)
        self.assertIn("public_id not in _FLOOD_SEMANTIC_PUBLIC_IDS", self.consumer)

    def test_class_scope_pairing_is_preserved_by_event_filter(self) -> None:
        self.assertIn("requested_flood_classes", self.consumer)
        self.assertIn("requested_flood_scopes", self.consumer)
        self.assertIn(
            'item["semantic_class"] in requested_flood_classes',
            self.consumer,
        )
        self.assertIn(
            'item["match_scope"] in requested_flood_scopes',
            self.consumer,
        )

    def test_consumer_normalization_preserves_flood_semantics(self) -> None:
        for marker in (
            'raw_flood_semantics = raw.get("flood_semantics")',
            '"semantic_class": semantic_class',
            '"match_scope": match_scope',
            'event["flood_semantics"] = normalized_flood_semantics',
        ):
            self.assertIn(marker, self.consumer)

    def test_diagnostics_expose_flood_dimensions(self) -> None:
        for marker in (
            '"flood_semantic_classes"',
            '"flood_match_scopes"',
            '"alert_stages"',
        ):
            self.assertIn(marker, self.diagnostic)

    def test_consumer_v1_schemas_are_synchronized(self) -> None:
        request_filters = self.resolve_schema["properties"]["event_filter"]["properties"]
        hazard_event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        hazard_filters = self.hazard_schema["properties"]["event_filter"]["properties"]
        capability_options = _find_event_filter_options(self.capabilities_schema)
        self.assertIsNotNone(capability_options)

        for field in ("flood_semantic_classes", "flood_match_scopes"):
            self.assertIn(field, request_filters)
            self.assertIn(field, hazard_filters)
            self.assertIn(field, capability_options)
        self.assertIn("flood_semantics", hazard_event)

    def test_glofas_is_not_promoted_to_official_event_semantics(self) -> None:
        self.assertNotIn("flood_semantics(", self.glofas)
        self.assertNotIn('"flood_semantics"', self.glofas)

    def test_provider_priority_and_cross_provider_dedup_are_not_introduced(self) -> None:
        runtime = (self.dwd + self.nws + self.nina + self.consumer).lower()
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
        self.assertEqual(backend.group(1), lab.group(1))
        self.assertEqual(backend.group(1), loader_build.group(1))
        self.assertEqual(loader_rev.group(1), loader.group(1))
        patch = int(backend.group(1).rsplit(".", 1)[1])
        loader_number = int(loader_rev.group(1).rsplit("-", 1)[1])
        self.assertGreaterEqual(patch, 126)
        self.assertGreaterEqual(loader_number, 129)


if __name__ == "__main__":
    unittest.main()
