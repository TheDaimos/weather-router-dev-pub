"""Contract tests for the P3-HAIL-40 runtime implementation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
RESOLVE_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resolve.request.schema.json"
HAZARD_SCHEMA_PATH = (
    ROOT / "contracts" / "consumer_v1" / "resources" / "hazard_feed.schema.json"
)
HAZARD_COMMON_PATH = (
    ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
)
DWD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "dwd.py"
NWS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_nws.py"
CONSUMER_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
DIAGNOSTIC_PATH = (
    ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
)
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"


def _load_hazard_common():
    spec = importlib.util.spec_from_file_location(
        "weather_router_hail_hazard_common_test",
        HAZARD_COMMON_PATH,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load hazard_common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P3HailImplementationTest(unittest.TestCase):
    """Protect additive Hail alert semantics without changing primary hazards."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.resolve_schema = json.loads(RESOLVE_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.hazard_schema = json.loads(HAZARD_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.hazard = _load_hazard_common()
        cls.dwd_source = DWD_PATH.read_text(encoding="utf-8")
        cls.nws_source = NWS_PATH.read_text(encoding="utf-8")
        cls.consumer_source = CONSUMER_PATH.read_text(encoding="utf-8")
        cls.diagnostic_source = DIAGNOSTIC_PATH.read_text(encoding="utf-8")
        cls.const_source = CONST_PATH.read_text(encoding="utf-8")

    def test_public_contract_count_and_candidate_set_remain_unchanged(self) -> None:
        self.assertEqual(self.mapping, self.contract)
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        self.assertFalse(
            any("hail" in item.casefold() for item in self.mapping["public_capabilities"])
        )
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

    def test_primary_hazard_order_is_preserved_for_combined_thunderstorm_hail(self) -> None:
        self.assertEqual(
            self.hazard.normalize_hazard_type(
                "Severe Thunderstorm Warning",
                "Large hail is expected.",
            ),
            "severe_thunderstorm",
        )

    def test_hail_semantic_class_is_independent_of_primary_hazard(self) -> None:
        self.assertEqual(
            self.hazard.hail_semantic_class(
                "Severe Thunderstorm Warning",
                "Large hail is expected.",
            ),
            "official_hail_alert_event",
        )
        self.assertIsNone(
            self.hazard.hail_semantic_class(
                "Severe Thunderstorm Warning",
                "Damaging winds are expected.",
            )
        )

    def test_hail_match_scope_explicit_event_has_precedence(self) -> None:
        self.assertEqual(
            self.hazard.hail_hazard_match_scope(
                event="Hail Warning",
                description="Large hail is expected.",
            ),
            "explicit_event",
        )
        self.assertEqual(
            self.hazard.hail_hazard_match_scope(
                headline="Severe Hail Warning",
                instruction="Protect vehicles from hail.",
            ),
            "explicit_event",
        )

    def test_hail_match_scope_contextual_text(self) -> None:
        self.assertEqual(
            self.hazard.hail_hazard_match_scope(
                event="Severe Thunderstorm Warning",
                description="Large hail is expected.",
            ),
            "contextual_text",
        )
        self.assertIsNone(
            self.hazard.hail_hazard_match_scope(
                event="Severe Thunderstorm Warning",
                description="Damaging winds are expected.",
            )
        )

    def test_dwd_adds_hail_semantics_without_replacing_tornado_semantics(self) -> None:
        for marker in (
            "hail_semantic_class(",
            "hail_hazard_match_scope(",
            '"hail_semantic_class"',
            '"hail_match_scope"',
            'event_payload.setdefault("alert_stage", "warning")',
            '_DWD_PROVIDER_REVISION = "wr-0.10.',
            "tornado_semantic_class(hazard_type)",
        ):
            self.assertIn(marker, self.dwd_source)

    def test_nws_adds_hail_semantics_and_reuses_alert_stage(self) -> None:
        for marker in (
            "hail_semantic_class(",
            "hail_hazard_match_scope(",
            '"hail_semantic_class"',
            '"hail_match_scope"',
            "normalize_alert_stage(event_name, headline)",
            "tornado_semantic_class(hazard_type)",
        ):
            self.assertIn(marker, self.nws_source)

    def test_consumer_filter_exposes_hail_dimensions(self) -> None:
        for marker in (
            '"hail_match_scopes"',
            '"hail_semantic_classes"',
            '"official_hail_alert_event"',
            '"explicit_event"',
            '"contextual_text"',
        ):
            self.assertIn(marker, self.consumer_source)

    def test_hail_filters_are_capability_gated_without_primary_hazard_requirement(self) -> None:
        self.assertIn("hail_dimensions", self.consumer_source)
        self.assertIn('"hail" not in allowed_types', self.consumer_source)
        self.assertIn(
            "Hagel-spezifische Event-Filter sind nur für öffentliche",
            self.consumer_source,
        )
        self.assertNotIn(
            'event_filter.get("hazard_types") == {"hail"}',
            self.consumer_source,
        )

    def test_consumer_normalization_preserves_hail_event_semantics(self) -> None:
        for marker in (
            '"hail_semantic_class"',
            '"hail_match_scope"',
            'event[semantic_key] = raw.get(semantic_key)',
        ):
            self.assertIn(marker, self.consumer_source)

    def test_diagnostics_expose_hail_dimensions(self) -> None:
        for marker in (
            '"hail_semantic_classes"',
            '"hail_match_scopes"',
            '"alert_stages"',
        ):
            self.assertIn(marker, self.diagnostic_source)

    def test_resolve_request_schema_exposes_hail_and_existing_alert_filters(self) -> None:
        props = self.resolve_schema["properties"]["event_filter"]["properties"]
        for field in (
            "alert_stages",
            "hazard_match_scopes",
            "tornado_semantic_classes",
            "hail_match_scopes",
            "hail_semantic_classes",
        ):
            self.assertIn(field, props)

    def test_hazard_feed_schema_preserves_hail_event_fields_and_filters(self) -> None:
        event_props = self.hazard_schema["properties"]["events"]["items"]["properties"]
        for field in (
            "alert_stage",
            "tornado_semantic_class",
            "hazard_match_scope",
            "hail_semantic_class",
            "hail_match_scope",
        ):
            self.assertIn(field, event_props)
        filter_props = self.hazard_schema["properties"]["event_filter"]["properties"]
        self.assertIn("hail_match_scopes", filter_props)
        self.assertIn("hail_semantic_classes", filter_props)

    def test_runtime_version_is_bumped(self) -> None:
        self.assertRegex(self.const_source, r'DEV_BUILD_VERSION: Final = "0\.10\.\d+"')
        self.assertRegex(self.const_source, r'DEV_LOADER_REV: Final = "0\.10-loader-\d+"')

    def test_no_observation_size_radar_or_probability_promotion(self) -> None:
        raw = (
            self.consumer_source
            + self.dwd_source
            + self.nws_source
        ).lower()
        for forbidden in (
            "observed_or_reported_hail_event",
            "hail_size_measurement_or_forecast",
            "radar_hail_signature",
            "hail_probability_forecast",
            "preferred_provider",
            "provider_priority",
        ):
            self.assertNotIn(forbidden, raw)


if __name__ == "__main__":
    unittest.main()
