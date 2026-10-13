"""Independent static acceptance tests for P4-FLOOD-50."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p4_flood_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_MAP_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
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
        "weather_router_p4_flood_static_acceptance",
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


class P4FloodStaticAcceptanceTest(unittest.TestCase):
    """Re-verify P4-FLOOD runtime independently from implementation tests."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract_mapping = json.loads(CONTRACT_MAP_PATH.read_text(encoding="utf-8"))
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

    def test_public_map_is_synchronized_and_no_new_id_was_added(self) -> None:
        self.assertEqual(self.mapping, self.contract_mapping)
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        self.assertEqual(self.design["public_capabilities_added"], 0)

    def test_flood_warning_transports_remain_distinct(self) -> None:
        transports = self.design["official_event_transports"]
        self.assertEqual(
            transports["weather.warning.official"]["candidates"],
            ["dwd/official_weather_warnings", "noaa_nws/official_weather_alerts"],
        )
        self.assertEqual(
            transports["natural_hazards.flood.warning"]["candidates"],
            ["nina_flood/flood_information_germany"],
        )
        self.assertEqual(
            transports["weather.warning.official"]["relationship"],
            "complementary",
        )
        self.assertEqual(
            transports["natural_hazards.flood.warning"]["relationship"],
            "dedicated_germany_flood_view",
        )

    def test_semantic_class_set_matches_design_exactly(self) -> None:
        self.assertEqual(
            self.design["event_semantics"]["semantic_classes"],
            [
                "official_flood_alert_event",
                "official_flash_flood_alert_event",
                "official_surface_water_flood_alert_event",
                "official_debris_flow_alert_event",
                "official_levee_failure_alert_event",
                "official_dam_failure_alert_event",
                "official_glof_alert_event",
                "official_ice_jam_flood_alert_event",
            ],
        )
        self.assertTrue(self.design["event_semantics"]["allow_multiple_classes_per_event"])
        self.assertTrue(self.design["event_semantics"]["preserve_class_scope_pairing"])

    def test_specific_compound_terms_do_not_create_generic_flood_false_positive(self) -> None:
        cases = {
            "Flash Flood Warning": "official_flash_flood_alert_event",
            "Surface Water Flood Warning": "official_surface_water_flood_alert_event",
            "Ice Jam Flood Warning": "official_ice_jam_flood_alert_event",
        }
        for text, expected_class in cases.items():
            result = self.hazard.flood_semantics(event=text)
            self.assertEqual([item["semantic_class"] for item in result], [expected_class])
            self.assertNotIn(
                "official_flood_alert_event",
                [item["semantic_class"] for item in result],
            )

    def test_generic_flood_requires_independent_generic_evidence(self) -> None:
        result = self.hazard.flood_semantics(
            event="Flood Warning",
            description="Flash flood possible in tributaries.",
        )
        self.assertIn(
            {
                "semantic_class": "official_flood_alert_event",
                "match_scope": "explicit_event",
            },
            result,
        )
        self.assertIn(
            {
                "semantic_class": "official_flash_flood_alert_event",
                "match_scope": "contextual_text",
            },
            result,
        )

    def test_multiple_specific_classes_and_pairing_survive(self) -> None:
        result = self.hazard.flood_semantics(
            event="Dam Failure Warning",
            description="Flash flood and debris flow expected.",
        )
        self.assertEqual(
            result,
            [
                {
                    "semantic_class": "official_dam_failure_alert_event",
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

    def test_heavy_rain_storm_surge_and_coastal_flood_do_not_infer_p4_flood(self) -> None:
        for text in (
            "Heavy Rain Warning",
            "Storm Surge Warning",
            "Coastal Flood Warning",
        ):
            self.assertEqual(self.hazard.flood_semantics(event=text), [])

    def test_nina_reachability_fix_has_no_synthetic_specific_fallback(self) -> None:
        for marker in (
            '"glacial_lake_outburst_flood"',
            '"ice_jam_flood"',
            '"glof"',
            '"gletscherseeausbruch"',
            '"ice jam flood"',
            '"eisstau"',
        ):
            self.assertIn(marker, self.bbk)
        self.assertIn("return \"civil_protection\"", self.bbk)

    def test_provider_adapters_preserve_real_source_evidence(self) -> None:
        for source in (self.dwd, self.nws):
            self.assertIn("flood_semantics(", source)
            self.assertIn('"flood_semantics"', source)

        self.assertRegex(
            self.dwd,
            r'_DWD_PROVIDER_REVISION = "wr-0\.10\.\d+-[^"]*semantics-1"',
        )
        self.assertIn('event_payload.setdefault("alert_stage", "warning")', self.dwd)
        self.assertIn("normalize_alert_stage(event_name, headline)", self.nws)

        self.assertRegex(
            self.nina,
            r'revision = "wr-0\.10\.\d+-[^"]*semantics-1"',
        )
        self.assertIn(
            'flood_semantics(headline=event.get("headline"))',
            self.nina,
        )

    def test_existing_p3_additive_dimensions_are_still_present(self) -> None:
        for source in (self.dwd, self.nws):
            for marker in (
                "tornado_semantic_class(",
                "hail_semantic_class(",
                "wind_hazard_semantic_class(",
                "supercell_semantic_class(",
            ):
                self.assertIn(marker, source)

    def test_consumer_filter_capability_gate_is_exact(self) -> None:
        for public_id in (
            "weather.warning.official",
            "natural_hazards.flood.warning",
            "civil_protection.warning.official",
        ):
            self.assertIn(f'"{public_id}"', self.consumer)
        self.assertIn("public_id not in _FLOOD_SEMANTIC_PUBLIC_IDS", self.consumer)
        self.assertEqual(
            set(self.design["event_filter_additions"]["compatible_public_capabilities"]),
            {
                "weather.warning.official",
                "natural_hazards.flood.warning",
                "civil_protection.warning.official",
            },
        )

    def test_consumer_filter_requires_class_scope_match_on_same_item(self) -> None:
        for marker in (
            "requested_flood_classes",
            "requested_flood_scopes",
            'item["semantic_class"] in requested_flood_classes',
            'item["match_scope"] in requested_flood_scopes',
        ):
            self.assertIn(marker, self.consumer)

    def test_consumer_preserves_only_known_flood_semantics(self) -> None:
        for marker in (
            'raw_flood_semantics = raw.get("flood_semantics")',
            "semantic_class in _FLOOD_SEMANTIC_CLASSES",
            "match_scope in _FLOOD_MATCH_SCOPES",
            'event["flood_semantics"] = normalized_flood_semantics',
        ):
            self.assertIn(marker, self.consumer)

    def test_diagnostics_and_public_schemas_are_synchronized(self) -> None:
        self.assertIn('"flood_semantic_classes"', self.diagnostic)
        self.assertIn('"flood_match_scopes"', self.diagnostic)

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

    def test_glofas_does_not_gain_official_event_semantics(self) -> None:
        self.assertNotIn("flood_semantics(", self.glofas)
        self.assertNotIn('"flood_semantics"', self.glofas)
        self.assertFalse(self.design["provider_design"]["glofas"]["official_event_semantics"])

    def test_no_provider_priority_or_cross_provider_deduplication(self) -> None:
        runtime = (self.dwd + self.nws + self.nina + self.consumer).lower()
        for forbidden in ("preferred_provider", "provider_priority", "cross_provider_dedup"):
            self.assertNotIn(forbidden, runtime)

    def test_backend_lab_and_loader_versions_are_synchronized_without_future_pin(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
