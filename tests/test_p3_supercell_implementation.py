"""Contract tests for the P3-SUPERCELL-40 runtime implementation."""

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
        "weather_router_supercell_hazard_common_test",
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


class P3SupercellImplementationTest(unittest.TestCase):
    """Protect additive Supercell semantics and Mesocyclone separation."""

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

    def test_primary_order_is_preserved(self) -> None:
        waterspout = self.hazard_source.index('"waterspout"')
        tornado = self.hazard_source.index('"tornado"')
        supercell = self.hazard_source.index('"supercell"')
        downburst = self.hazard_source.index('"downburst"')
        severe = self.hazard_source.index('"severe_thunderstorm"')
        hail = self.hazard_source.index('("hail", ("hail", "hagel"))')
        self.assertLess(waterspout, tornado)
        self.assertLess(tornado, supercell)
        self.assertLess(supercell, downburst)
        self.assertLess(downburst, severe)
        self.assertLess(severe, hail)

    def test_primary_supercell_no_longer_uses_mesocyclone_alias(self) -> None:
        self.assertEqual(
            self.hazard.normalize_hazard_type("Supercell Warning"),
            "supercell",
        )
        self.assertEqual(
            self.hazard.normalize_hazard_type("Superzelle erkannt"),
            "supercell",
        )
        self.assertNotEqual(
            self.hazard.normalize_hazard_type("Mesocyclone detected"),
            "supercell",
        )
        self.assertNotEqual(
            self.hazard.normalize_hazard_type("Mesozyklone erkannt"),
            "supercell",
        )

    def test_tornado_primary_can_keep_additive_supercell_semantics(self) -> None:
        event = "Tornado Warning"
        description = "This tornado is associated with a dangerous supercell."
        self.assertEqual(self.hazard.normalize_hazard_type(event, description), "tornado")
        self.assertEqual(
            self.hazard.supercell_semantic_class(event, description),
            "official_supercell_alert_event",
        )
        self.assertEqual(
            self.hazard.supercell_hazard_match_scope(
                event=event,
                description=description,
            ),
            "contextual_text",
        )

    def test_explicit_supercell_evidence_is_explicit_scope(self) -> None:
        self.assertEqual(
            self.hazard.supercell_semantic_class("Supercell Warning"),
            "official_supercell_alert_event",
        )
        self.assertEqual(
            self.hazard.supercell_hazard_match_scope(event="Supercell Warning"),
            "explicit_event",
        )

    def test_mesocyclone_is_not_supercell_semantic_evidence(self) -> None:
        self.assertIsNone(
            self.hazard.supercell_semantic_class(
                "Weather Statement",
                "A mesocyclone is detected by radar.",
            )
        )
        self.assertIsNone(
            self.hazard.supercell_hazard_match_scope(
                event="Weather Statement",
                description="A mesocyclone is detected by radar.",
            )
        )

    def test_dwd_adds_supercell_semantics_and_revision(self) -> None:
        for marker in (
            "supercell_semantic_class(",
            "supercell_hazard_match_scope(",
            '"supercell_semantic_class"',
            '"supercell_match_scope"',
            'event_payload.setdefault("alert_stage", "warning")',
            '_DWD_PROVIDER_REVISION = "wr-0.10.',
        ):
            self.assertIn(marker, self.dwd)

    def test_nws_adds_supercell_semantics_and_reuses_alert_stage(self) -> None:
        for marker in (
            "supercell_semantic_class(",
            "supercell_hazard_match_scope(",
            '"supercell_semantic_class"',
            '"supercell_match_scope"',
            "normalize_alert_stage(event_name, headline)",
        ):
            self.assertIn(marker, self.nws)

    def test_consumer_filter_exposes_supercell_dimensions(self) -> None:
        for marker in (
            '"supercell_match_scopes"',
            '"supercell_semantic_classes"',
            '"official_supercell_alert_event"',
            "supercell_dimensions",
        ):
            self.assertIn(marker, self.consumer)

    def test_supercell_filter_is_capability_gated_not_primary_label_gated(self) -> None:
        self.assertIn('"supercell"', self.consumer)
        self.assertIn("supercell_dimensions", self.consumer)
        self.assertNotIn(
            'event_filter.get("hazard_types") == {"supercell"}',
            self.consumer,
        )

    def test_consumer_normalization_preserves_supercell_fields(self) -> None:
        for marker in (
            '"supercell_semantic_class"',
            '"supercell_match_scope"',
            'event[semantic_key] = raw.get(semantic_key)',
        ):
            self.assertIn(marker, self.consumer)

    def test_diagnostics_expose_supercell_dimensions(self) -> None:
        for marker in (
            '"supercell_semantic_classes"',
            '"supercell_match_scopes"',
            '"alert_stages"',
        ):
            self.assertIn(marker, self.diagnostic)

    def test_public_schemas_expose_supercell_fields(self) -> None:
        request_filters = self.resolve_schema["properties"]["event_filter"]["properties"]
        hazard_event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        hazard_filters = self.hazard_schema["properties"]["event_filter"]["properties"]
        capability_options = _find_event_filter_options(self.capabilities_schema)
        self.assertIsNotNone(capability_options)

        for field in ("supercell_match_scopes", "supercell_semantic_classes"):
            self.assertIn(field, request_filters)
            self.assertIn(field, hazard_filters)
            self.assertIn(field, capability_options)

        for field in ("supercell_semantic_class", "supercell_match_scope"):
            self.assertIn(field, hazard_event)

    def test_related_thunder_contracts_remain_unchanged(self) -> None:
        cells = self.mapping["public_capabilities"]["weather.convection.thunderstorm_cells"]
        probability = self.mapping["public_capabilities"]["weather.point.thunder_probability"]
        self.assertIn(
            "tornado_hail_downburst_supercell_semantics",
            cells["intent_contract"]["non_guarantees"],
        )
        self.assertEqual(
            probability["intent_contract"]["quantity_policy"],
            "thunderstorm_probability",
        )

    def test_runtime_version_is_bumped(self) -> None:
        self.assertRegex(self.const, r'DEV_BUILD_VERSION: Final = "0\.10\.\d+"')
        self.assertRegex(self.const, r'DEV_LOADER_REV: Final = "0\.10-loader-\d+"')

    def test_forbidden_promotions_are_absent_from_runtime(self) -> None:
        runtime = (self.hazard_source + self.dwd + self.nws + self.consumer).lower()
        for forbidden in (
            "confirmed_supercell_observation_event",
            "observed_or_reported_supercell_event",
            "supercell_probability_forecast",
            "preferred_provider",
            "provider_priority",
        ):
            self.assertNotIn(forbidden, runtime)


if __name__ == "__main__":
    unittest.main()
