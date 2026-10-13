"""Independent static acceptance tests for P3-WINDHAZ-50."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p3_windhaz_intent_design.v1.json"
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
        "weather_router_windhaz_static_acceptance",
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


class P3WindHazStaticAcceptanceTest(unittest.TestCase):
    """Re-verify P3-WINDHAZ runtime against design and negative boundaries."""

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

    def test_public_contract_and_candidate_set_are_unchanged(self) -> None:
        self.assertEqual(self.mapping, self.contract_mapping)
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        self.assertEqual(self.design["public_capabilities_added"], 0)
        warning = self.mapping["public_capabilities"]["weather.warning.official"]
        self.assertEqual(warning["strategy"], "aggregate")
        actual = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if "weather.warning.official" in public_ids:
                    actual.append(f"{provider_id}/{capability_id}")
        self.assertEqual(
            actual,
            ["dwd/official_weather_warnings", "noaa_nws/official_weather_alerts"],
        )

    def test_primary_hazard_order_is_preserved(self) -> None:
        downburst = self.hazard_source.index('"downburst"')
        severe = self.hazard_source.index('"severe_thunderstorm"')
        windstorm = self.hazard_source.index('"windstorm"')
        self.assertLess(downburst, severe)
        self.assertLess(severe, windstorm)
        self.assertFalse(self.design["primary_hazard_type"]["change"])
        self.assertFalse(self.design["primary_hazard_type"]["reorder_patterns"])

    def test_thunderstorm_warning_is_not_false_positive_storm_warning(self) -> None:
        self.assertIsNone(
            self.hazard.wind_hazard_semantic_class(
                "Severe Thunderstorm Warning",
                "Frequent lightning is occurring.",
            )
        )
        self.assertIsNone(
            self.hazard.wind_hazard_match_scope(
                event="Severe Thunderstorm Warning",
                description="Frequent lightning is occurring.",
            )
        )

    def test_thunderstorm_with_real_damaging_wind_gets_additive_wind_class(self) -> None:
        event = "Severe Thunderstorm Warning"
        description = "Damaging winds with wind gusts to 60 mph are expected."
        self.assertEqual(
            self.hazard.normalize_hazard_type(event, description),
            "severe_thunderstorm",
        )
        self.assertEqual(
            self.hazard.wind_hazard_semantic_class(event, description),
            "official_wind_alert_event",
        )
        self.assertEqual(
            self.hazard.wind_hazard_match_scope(
                event=event,
                description=description,
            ),
            "contextual_text",
        )

    def test_high_wind_warning_is_explicit(self) -> None:
        self.assertEqual(
            self.hazard.wind_hazard_semantic_class("High Wind Warning"),
            "official_wind_alert_event",
        )
        self.assertEqual(
            self.hazard.wind_hazard_match_scope(event="High Wind Warning"),
            "explicit_event",
        )

    def test_downburst_is_specific_and_has_precedence(self) -> None:
        self.assertEqual(
            self.hazard.wind_hazard_semantic_class(
                "High Wind Warning",
                "A microburst may occur.",
            ),
            "official_downburst_alert_event",
        )
        self.assertEqual(
            self.hazard.normalize_hazard_type(
                "Severe Thunderstorm Warning",
                "A downburst may produce destructive winds.",
            ),
            "downburst",
        )

    def test_generic_wind_and_storm_surge_are_not_promoted(self) -> None:
        self.assertIsNone(
            self.hazard.wind_hazard_semantic_class(
                "Weather Statement",
                "Wind variable at 10 mph.",
            )
        )
        self.assertIsNone(
            self.hazard.wind_hazard_semantic_class(
                "Sturmflutwarnung",
                "Erhöhte Wasserstände an der Küste.",
            )
        )

    def test_provider_adapters_match_design(self) -> None:
        for source in (self.dwd, self.nws):
            self.assertIn("wind_hazard_semantic_class(", source)
            self.assertIn("wind_hazard_match_scope(", source)
            self.assertIn('"wind_hazard_semantic_class"', source)
            self.assertIn('"wind_hazard_match_scope"', source)
            self.assertNotIn("preferred_provider", source.lower())
            self.assertNotIn("provider_priority", source.lower())
        self.assertRegex(
            self.dwd,
            r'_DWD_PROVIDER_REVISION = "wr-0\.10\.\d+-[a-z0-9_-]+-semantics-\d+"',
        )

    def test_consumer_filter_and_preservation_match_design(self) -> None:
        for marker in (
            '"wind_hazard_semantic_classes"',
            '"wind_hazard_match_scopes"',
            '"official_wind_alert_event"',
            '"official_downburst_alert_event"',
            '"wind_hazard_semantic_class"',
            '"wind_hazard_match_scope"',
            "wind_hazard_dimensions",
        ):
            self.assertIn(marker, self.consumer)

    def test_public_schemas_are_synchronized(self) -> None:
        request_filters = self.resolve_schema["properties"]["event_filter"]["properties"]
        hazard_event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        hazard_filters = self.hazard_schema["properties"]["event_filter"]["properties"]
        capability_options = _find_event_filter_options(self.capabilities_schema)
        self.assertIsNotNone(capability_options)
        for field in ("wind_hazard_semantic_classes", "wind_hazard_match_scopes"):
            self.assertIn(field, request_filters)
            self.assertIn(field, hazard_filters)
            self.assertIn(field, capability_options)
        for field in ("wind_hazard_semantic_class", "wind_hazard_match_scope"):
            self.assertIn(field, hazard_event)

    def test_diagnostics_and_alert_stage_are_present(self) -> None:
        for marker in (
            '"wind_hazard_semantic_classes"',
            '"wind_hazard_match_scopes"',
            '"alert_stages"',
        ):
            self.assertIn(marker, self.diagnostic)
        self.assertIn('event_payload.setdefault("alert_stage", "warning")', self.dwd)
        self.assertIn("normalize_alert_stage(event_name, headline)", self.nws)

    def test_p2_wind_numeric_contracts_are_unchanged(self) -> None:
        speed = self.mapping["public_capabilities"]["weather.point.wind_speed"]
        gust = self.mapping["public_capabilities"]["weather.point.wind_gusts"]
        direction = self.mapping["public_capabilities"]["weather.point.wind_direction"]
        self.assertEqual(speed["intent_contract"]["quantity_policy"], "wind_speed")
        self.assertEqual(speed["intent_contract"]["canonical_unit"], "m/s")
        self.assertEqual(gust["intent_contract"]["quantity_policy"], "wind_gust_speed")
        self.assertEqual(gust["intent_contract"]["canonical_unit"], "m/s")
        self.assertEqual(direction["intent_contract"]["quantity_policy"], "wind_from_direction")
        self.assertNotIn("warning_event", json.dumps([speed, gust, direction]))

    def test_forbidden_promotions_are_absent(self) -> None:
        runtime = (self.hazard_source + self.dwd + self.nws + self.consumer).lower()
        for forbidden in (
            "observed_or_reported_wind_damage_event",
            "confirmed_downburst_observation_event",
            "downburst_radar_or_nowcast_signature",
            "numeric_wind_threshold_warning_inference",
            "preferred_provider",
            "provider_priority",
        ):
            self.assertNotIn(forbidden, runtime)

    def test_runtime_version_is_exact(self) -> None:
        self.assertRegex(self.const, r'DEV_BUILD_VERSION: Final = "0\.10\.\d+"')
        self.assertRegex(self.const, r'DEV_LOADER_REV: Final = "0\.10-loader-\d+"')


if __name__ == "__main__":
    unittest.main()
