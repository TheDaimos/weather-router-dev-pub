"""Independent static acceptance tests for P3-HAIL-50."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p3_hail_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_MAP_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
HAZARD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
DWD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "dwd.py"
NWS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_nws.py"
CONSUMER_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
DIAGNOSTIC_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
RESOLVE_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resolve.request.schema.json"
HAZARD_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resources" / "hazard_feed.schema.json"
CAPABILITIES_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "capabilities.response.schema.json"
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"


def _load_hazard_common():
    spec = importlib.util.spec_from_file_location(
        "weather_router_hail_static_acceptance",
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


class P3HailStaticAcceptanceTest(unittest.TestCase):
    """Re-verify the P3-HAIL implementation against its design."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract_mapping = json.loads(CONTRACT_MAP_PATH.read_text(encoding="utf-8"))
        cls.hazard = _load_hazard_common()
        cls.hazard_source = HAZARD_PATH.read_text(encoding="utf-8")
        cls.dwd = DWD_PATH.read_text(encoding="utf-8")
        cls.nws = NWS_PATH.read_text(encoding="utf-8")
        cls.consumer = CONSUMER_PATH.read_text(encoding="utf-8")
        cls.diagnostic = DIAGNOSTIC_PATH.read_text(encoding="utf-8")
        cls.resolve_schema = json.loads(RESOLVE_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.hazard_schema = json.loads(HAZARD_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.capabilities_schema = json.loads(
            CAPABILITIES_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        cls.const = CONST_PATH.read_text(encoding="utf-8")

    def test_design_and_runtime_keep_public_contract_unchanged(self) -> None:
        self.assertEqual(self.mapping, self.contract_mapping)
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        self.assertEqual(self.design["public_capabilities_added"], 0)
        self.assertEqual(
            self.mapping["public_capabilities"]["weather.warning.official"]["strategy"],
            "aggregate",
        )

    def test_primary_hazard_order_is_still_unchanged(self) -> None:
        severe_pos = self.hazard_source.index('"severe_thunderstorm"')
        hail_pos = self.hazard_source.index('("hail", ("hail", "hagel"))')
        self.assertLess(severe_pos, hail_pos)
        self.assertEqual(
            self.hazard.normalize_hazard_type(
                "Severe Thunderstorm Warning",
                "Large hail expected.",
            ),
            "severe_thunderstorm",
        )

    def test_additive_hail_semantics_survive_primary_thunderstorm_label(self) -> None:
        self.assertEqual(
            self.hazard.hail_semantic_class(
                "Severe Thunderstorm Warning",
                "Large hail expected.",
            ),
            "official_hail_alert_event",
        )
        self.assertEqual(
            self.hazard.hail_hazard_match_scope(
                event="Severe Thunderstorm Warning",
                description="Large hail expected.",
            ),
            "contextual_text",
        )

    def test_provider_adapters_implement_the_design_without_priority(self) -> None:
        for source in (self.dwd, self.nws):
            self.assertIn("hail_semantic_class(", source)
            self.assertIn("hail_hazard_match_scope(", source)
            self.assertIn('"hail_semantic_class"', source)
            self.assertIn('"hail_match_scope"', source)
            self.assertNotIn("preferred_provider", source.lower())
            self.assertNotIn("provider_priority", source.lower())
        self.assertRegex(
            self.dwd,
            r'_DWD_PROVIDER_REVISION = "wr-0\.10\.\d+-[a-z0-9_-]+-semantics-\d+"',
        )

    def test_consumer_filter_and_preservation_match_design(self) -> None:
        for marker in (
            '"hail_semantic_classes"',
            '"hail_match_scopes"',
            '"official_hail_alert_event"',
            '"hail_semantic_class"',
            '"hail_match_scope"',
            "hail_dimensions",
        ):
            self.assertIn(marker, self.consumer)
        self.assertIn(
            'event_payload.setdefault("alert_stage", "warning")',
            self.dwd,
        )

    def test_diagnostics_expose_required_hail_dimensions(self) -> None:
        for marker in (
            '"hail_semantic_classes"',
            '"hail_match_scopes"',
            '"alert_stages"',
        ):
            self.assertIn(marker, self.diagnostic)

    def test_public_schemas_are_synchronized(self) -> None:
        request_filters = self.resolve_schema["properties"]["event_filter"]["properties"]
        hazard_event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        hazard_filters = self.hazard_schema["properties"]["event_filter"]["properties"]
        capability_options = _find_event_filter_options(self.capabilities_schema)
        self.assertIsNotNone(capability_options)

        for field in (
            "alert_stages",
            "hazard_match_scopes",
            "tornado_semantic_classes",
            "hail_match_scopes",
            "hail_semantic_classes",
        ):
            self.assertIn(field, request_filters)
            self.assertIn(field, hazard_filters)
            self.assertIn(field, capability_options)

        for field in (
            "alert_stage",
            "tornado_semantic_class",
            "hazard_match_scope",
            "hail_semantic_class",
            "hail_match_scope",
        ):
            self.assertIn(field, hazard_event)

    def test_hail_filter_is_not_tied_to_primary_hazard_type(self) -> None:
        self.assertIn('"hail" not in allowed_types', self.consumer)
        self.assertNotIn(
            'event_filter.get("hazard_types") == {"hail"}',
            self.consumer,
        )
        self.assertTrue(
            self.design["event_filter_additions"][
                "specialized_hail_filter_does_not_require_hazard_type_hail"
            ]
        )

    def test_forbidden_hail_promotions_are_absent_from_runtime(self) -> None:
        runtime = (self.hazard_source + self.dwd + self.nws + self.consumer).lower()
        for forbidden in (
            "observed_or_reported_hail_event",
            "hail_size_measurement_or_forecast",
            "radar_hail_signature",
            "hail_probability_forecast",
        ):
            self.assertNotIn(forbidden, runtime)

    def test_runtime_version_is_exact(self) -> None:
        self.assertRegex(self.const, r'DEV_BUILD_VERSION: Final = "0\.10\.\d+"')
        self.assertRegex(self.const, r'DEV_LOADER_REV: Final = "0\.10-loader-\d+"')

    def test_core_invariants_remain_unchanged(self) -> None:
        invariants = set(self.design["invariants"])
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)
        self.assertIn("Coverage unknown remains unknown.", invariants)
        self.assertIn("Endpoint reachability is not coverage proof.", invariants)


if __name__ == "__main__":
    unittest.main()
