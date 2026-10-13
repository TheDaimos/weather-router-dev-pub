"""Contract tests for the P3-TORNADO-40 runtime implementation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
HAZARD_COMMON_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
DWD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "dwd.py"
NWS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_nws.py"
CONSUMER_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
DIAGNOSTIC_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"


def _load_hazard_common():
    spec = importlib.util.spec_from_file_location(
        "weather_router_tornado_hazard_common_test",
        HAZARD_COMMON_PATH,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load hazard_common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P3TornadoImplementationTest(unittest.TestCase):
    """Protect additive Tornado/Waterspout alert semantics."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.hazard = _load_hazard_common()
        cls.dwd_source = DWD_PATH.read_text(encoding="utf-8")
        cls.nws_source = NWS_PATH.read_text(encoding="utf-8")
        cls.consumer_source = CONSUMER_PATH.read_text(encoding="utf-8")
        cls.diagnostic_source = DIAGNOSTIC_PATH.read_text(encoding="utf-8")
        cls.const_source = CONST_PATH.read_text(encoding="utf-8")

    def test_public_contract_count_and_map_remain_unchanged(self) -> None:
        self.assertEqual(self.mapping, self.contract)
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        self.assertNotIn("weather.tornado", self.mapping["public_capabilities"])

    def test_warning_candidate_set_remains_dwd_and_nws(self) -> None:
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
        self.assertEqual(
            self.mapping["public_capabilities"]["weather.warning.official"]["strategy"],
            "aggregate",
        )

    def test_semantic_class_keeps_tornado_and_waterspout_distinct(self) -> None:
        self.assertEqual(
            self.hazard.tornado_semantic_class("tornado"),
            "official_tornado_alert_event",
        )
        self.assertEqual(
            self.hazard.tornado_semantic_class("waterspout"),
            "official_waterspout_alert_event",
        )
        self.assertIsNone(self.hazard.tornado_semantic_class("hail"))

    def test_alert_stage_normalization_order(self) -> None:
        self.assertEqual(
            self.hazard.normalize_alert_stage("Tornado Warning"),
            "warning",
        )
        self.assertEqual(
            self.hazard.normalize_alert_stage("Tornado Watch"),
            "watch",
        )
        self.assertEqual(
            self.hazard.normalize_alert_stage("Convective Outlook"),
            "outlook",
        )
        self.assertEqual(
            self.hazard.normalize_alert_stage("Tornado Statement Update"),
            "statement",
        )
        self.assertEqual(
            self.hazard.normalize_alert_stage("Tornado information"),
            "unspecified",
        )

    def test_hazard_match_scope_explicit_event(self) -> None:
        self.assertEqual(
            self.hazard.tornado_hazard_match_scope(
                "tornado",
                event="Tornado Warning",
                description="Possible severe weather.",
            ),
            "explicit_event",
        )
        self.assertEqual(
            self.hazard.tornado_hazard_match_scope(
                "waterspout",
                headline="Waterspout Warning",
            ),
            "explicit_event",
        )

    def test_hazard_match_scope_contextual_text(self) -> None:
        self.assertEqual(
            self.hazard.tornado_hazard_match_scope(
                "tornado",
                event="Severe Weather Warning",
                description="A tornado is possible.",
            ),
            "contextual_text",
        )
        self.assertEqual(
            self.hazard.tornado_hazard_match_scope(
                "waterspout",
                headline="Marine Warning",
                instruction="Seek shelter from a waterspout.",
            ),
            "contextual_text",
        )

    def test_non_tornado_event_has_no_tornado_match_scope(self) -> None:
        self.assertIsNone(
            self.hazard.tornado_hazard_match_scope(
                "hail",
                event="Tornado Warning",
            )
        )

    def test_dwd_adds_only_broad_official_alert_semantics(self) -> None:
        for marker in (
            "tornado_semantic_class(hazard_type)",
            '"alert_stage": "warning"',
            "tornado_hazard_match_scope(",
            '_DWD_PROVIDER_REVISION = "wr-0.10.',
        ):
            self.assertIn(marker, self.dwd_source)
        self.assertNotIn("confirmed_tornado_observation_event", self.dwd_source)
        self.assertNotIn("radar_rotation_signature", self.dwd_source)

    def test_nws_normalizes_stage_from_event_and_headline(self) -> None:
        for marker in (
            "normalize_alert_stage(event_name, headline)",
            "tornado_semantic_class(hazard_type)",
            "tornado_hazard_match_scope(",
        ):
            self.assertIn(marker, self.nws_source)
        self.assertNotIn("confirmed_tornado_observation_event", self.nws_source)

    def test_consumer_filter_exposes_all_three_new_dimensions(self) -> None:
        for marker in (
            '"alert_stages"',
            '"hazard_match_scopes"',
            '"tornado_semantic_classes"',
            '"warning"',
            '"watch"',
            '"outlook"',
            '"statement"',
            '"unspecified"',
            '"explicit_event"',
            '"contextual_text"',
            '"official_tornado_alert_event"',
            '"official_waterspout_alert_event"',
        ):
            self.assertIn(marker, self.consumer_source)

    def test_hazard_normalization_preserves_tornado_event_semantics(self) -> None:
        for marker in (
            '"tornado_semantic_class"',
            '"alert_stage"',
            '"hazard_match_scope"',
            'for semantic_key in (',
            'event[semantic_key] = raw.get(semantic_key)',
        ):
            self.assertIn(marker, self.consumer_source)

    def test_tornado_filters_are_capability_gated(self) -> None:
        self.assertIn("tornado_dimensions", self.consumer_source)
        self.assertIn('"tornado",', self.consumer_source)
        self.assertIn('"waterspout",', self.consumer_source)
        self.assertIn(
            "Tornado-spezifische Event-Filter sind nur für öffentliche",
            self.consumer_source,
        )

    def test_diagnostics_expose_all_new_dimensions(self) -> None:
        for marker in (
            '"alert_stages"',
            '"tornado_semantic_classes"',
            '"hazard_match_scopes"',
        ):
            self.assertIn(marker, self.diagnostic_source)

    def test_runtime_version_is_bumped(self) -> None:
        self.assertRegex(self.const_source, r'DEV_BUILD_VERSION: Final = "0\.10\.\d+"')
        self.assertRegex(self.const_source, r'DEV_LOADER_REV: Final = "0\.10-loader-\d+"')

    def test_no_provider_priority_or_confirmed_tornado_promotion(self) -> None:
        raw = (
            self.consumer_source
            + self.dwd_source
            + self.nws_source
        ).lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("provider_priority", raw)
        self.assertNotIn("confirmed_tornado_observation_event", raw)
        self.assertNotIn("radar_rotation_signature", raw)


if __name__ == "__main__":
    unittest.main()
