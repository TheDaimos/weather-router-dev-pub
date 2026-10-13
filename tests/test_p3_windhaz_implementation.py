"""Contract tests for the P3-WINDHAZ-40 runtime implementation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
RESOLVE_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resolve.request.schema.json"
HAZARD_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resources" / "hazard_feed.schema.json"
CAPABILITIES_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "capabilities.response.schema.json"
HAZARD_COMMON_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
DWD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "dwd.py"
NWS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_nws.py"
CONSUMER_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
DIAGNOSTIC_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"


def _load_hazard_common():
    spec = importlib.util.spec_from_file_location(
        "weather_router_windhaz_hazard_common_test",
        HAZARD_COMMON_PATH,
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


class P3WindHazImplementationTest(unittest.TestCase):
    """Protect additive severe-wind/downburst semantics without regressions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.resolve_schema = json.loads(RESOLVE_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.hazard_schema = json.loads(HAZARD_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.capabilities_schema = json.loads(
            CAPABILITIES_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        cls.hazard = _load_hazard_common()
        cls.hazard_source = HAZARD_COMMON_PATH.read_text(encoding="utf-8")
        cls.dwd = DWD_PATH.read_text(encoding="utf-8")
        cls.nws = NWS_PATH.read_text(encoding="utf-8")
        cls.consumer = CONSUMER_PATH.read_text(encoding="utf-8")
        cls.diagnostic = DIAGNOSTIC_PATH.read_text(encoding="utf-8")
        cls.const = CONST_PATH.read_text(encoding="utf-8")

    def test_public_contract_and_warning_candidates_remain_unchanged(self) -> None:
        self.assertEqual(self.mapping, self.contract)
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        actual = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if "weather.warning.official" in public_ids:
                    actual.append(f"{provider_id}/{capability_id}")
        self.assertEqual(
            actual,
            [
                "dwd/official_weather_warnings",
                "noaa_nws/official_weather_alerts",
            ],
        )

    def test_primary_hazard_order_remains_downburst_thunderstorm_windstorm(self) -> None:
        downburst = self.hazard_source.index('"downburst"')
        severe = self.hazard_source.index('"severe_thunderstorm"')
        windstorm = self.hazard_source.index('"windstorm"')
        self.assertLess(downburst, severe)
        self.assertLess(severe, windstorm)

    def test_severe_thunderstorm_keeps_primary_label_but_adds_wind_hazard(self) -> None:
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

    def test_high_wind_warning_is_explicit_broad_wind_alert(self) -> None:
        self.assertEqual(
            self.hazard.wind_hazard_semantic_class("High Wind Warning"),
            "official_wind_alert_event",
        )
        self.assertEqual(
            self.hazard.wind_hazard_match_scope(event="High Wind Warning"),
            "explicit_event",
        )

    def test_specific_downburst_takes_precedence_over_broad_wind(self) -> None:
        event = "High Wind Warning"
        description = "A microburst is possible in the warned area."
        self.assertEqual(
            self.hazard.wind_hazard_semantic_class(event, description),
            "official_downburst_alert_event",
        )
        self.assertEqual(
            self.hazard.wind_hazard_match_scope(
                event=event,
                description=description,
            ),
            "contextual_text",
        )

    def test_explicit_downburst_remains_primary_downburst(self) -> None:
        self.assertEqual(
            self.hazard.normalize_hazard_type(
                "Severe Thunderstorm Warning",
                "A downburst may produce destructive winds.",
            ),
            "downburst",
        )
        self.assertEqual(
            self.hazard.wind_hazard_semantic_class(
                "Severe Thunderstorm Warning",
                "A downburst may produce destructive winds.",
            ),
            "official_downburst_alert_event",
        )

    def test_isolated_wind_and_storm_surge_do_not_trigger_additive_wind_hazard(self) -> None:
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

    def test_dwd_adds_wind_hazard_semantics_and_revision(self) -> None:
        for marker in (
            "wind_hazard_semantic_class(",
            "wind_hazard_match_scope(",
            '"wind_hazard_semantic_class"',
            '"wind_hazard_match_scope"',
            'event_payload.setdefault("alert_stage", "warning")',
            '_DWD_PROVIDER_REVISION = "wr-0.10.',
        ):
            self.assertIn(marker, self.dwd)

    def test_nws_adds_wind_hazard_semantics_and_reuses_alert_stage(self) -> None:
        for marker in (
            "wind_hazard_semantic_class(",
            "wind_hazard_match_scope(",
            '"wind_hazard_semantic_class"',
            '"wind_hazard_match_scope"',
            "normalize_alert_stage(event_name, headline)",
        ):
            self.assertIn(marker, self.nws)

    def test_consumer_filter_exposes_wind_hazard_dimensions(self) -> None:
        for marker in (
            '"wind_hazard_match_scopes"',
            '"wind_hazard_semantic_classes"',
            '"official_wind_alert_event"',
            '"official_downburst_alert_event"',
            "wind_hazard_dimensions",
        ):
            self.assertIn(marker, self.consumer)

    def test_wind_hazard_filter_is_capability_gated_not_primary_label_gated(self) -> None:
        self.assertIn('"windstorm"', self.consumer)
        self.assertIn('"downburst"', self.consumer)
        self.assertIn("wind_hazard_dimensions", self.consumer)
        self.assertNotIn(
            'event_filter.get("hazard_types") == {"windstorm"}',
            self.consumer,
        )
        self.assertNotIn(
            'event_filter.get("hazard_types") == {"downburst"}',
            self.consumer,
        )

    def test_consumer_normalization_preserves_wind_hazard_fields(self) -> None:
        for marker in (
            '"wind_hazard_semantic_class"',
            '"wind_hazard_match_scope"',
            'event[semantic_key] = raw.get(semantic_key)',
        ):
            self.assertIn(marker, self.consumer)

    def test_diagnostics_expose_wind_hazard_dimensions(self) -> None:
        for marker in (
            '"wind_hazard_semantic_classes"',
            '"wind_hazard_match_scopes"',
            '"alert_stages"',
        ):
            self.assertIn(marker, self.diagnostic)

    def test_public_schemas_expose_wind_hazard_fields(self) -> None:
        request_filters = self.resolve_schema["properties"]["event_filter"]["properties"]
        hazard_event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        hazard_filters = self.hazard_schema["properties"]["event_filter"]["properties"]
        capability_options = _find_event_filter_options(self.capabilities_schema)
        self.assertIsNotNone(capability_options)

        for field in (
            "wind_hazard_match_scopes",
            "wind_hazard_semantic_classes",
        ):
            self.assertIn(field, request_filters)
            self.assertIn(field, hazard_filters)
            self.assertIn(field, capability_options)

        for field in (
            "wind_hazard_semantic_class",
            "wind_hazard_match_scope",
        ):
            self.assertIn(field, hazard_event)

    def test_p2_wind_numeric_contracts_remain_unchanged(self) -> None:
        gust = self.mapping["public_capabilities"]["weather.point.wind_gusts"]
        self.assertEqual(gust["intent_contract"]["quantity_policy"], "wind_gust_speed")
        self.assertEqual(gust["intent_contract"]["canonical_unit"], "m/s")
        self.assertEqual(gust["intent_contract"]["observation_kind_policy"], "forecast")
        self.assertNotIn("warning_event", json.dumps(gust))

    def test_runtime_version_is_bumped(self) -> None:
        self.assertRegex(self.const, r'DEV_BUILD_VERSION: Final = "0\.10\.\d+"')
        self.assertRegex(self.const, r'DEV_LOADER_REV: Final = "0\.10-loader-\d+"')

    def test_forbidden_promotions_are_absent_from_runtime(self) -> None:
        runtime = (
            self.hazard_source
            + self.dwd
            + self.nws
            + self.consumer
        ).lower()
        for forbidden in (
            "observed_or_reported_wind_damage_event",
            "confirmed_downburst_observation_event",
            "downburst_radar_or_nowcast_signature",
            "numeric_wind_threshold_warning_inference",
            "preferred_provider",
            "provider_priority",
        ):
            self.assertNotIn(forbidden, runtime)


if __name__ == "__main__":
    unittest.main()
