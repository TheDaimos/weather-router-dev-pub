"""Independent static acceptance tests for P3-SUPERCELL-50."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p3_supercell_intent_design.v1.json"
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
        "weather_router_supercell_static_acceptance",
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


class P3SupercellStaticAcceptanceTest(unittest.TestCase):
    """Re-verify Supercell runtime against design and negative boundaries."""

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
        self.assertIn("supercell", warning["hazard_types"])
        actual = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if "weather.warning.official" in public_ids:
                    actual.append(f"{provider_id}/{capability_id}")
        self.assertEqual(
            actual,
            ["dwd/official_weather_warnings", "noaa_nws/official_weather_alerts"],
        )

    def test_primary_order_is_preserved_but_mesocyclone_aliases_are_removed(self) -> None:
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
        self.assertFalse(self.design["primary_hazard_type"]["reorder_patterns"])
        self.assertTrue(
            self.design["primary_hazard_type"][
                "remove_mesocyclone_aliases_from_supercell"
            ]
        )
        self.assertEqual(
            self.design["primary_hazard_type"]["supercell_keywords_after"],
            ["supercell", "superzelle"],
        )

    def test_mesocyclone_is_not_promoted_to_supercell(self) -> None:
        for text in ("Mesocyclone detected by radar", "Mesozyklone erkannt"):
            self.assertNotEqual(self.hazard.normalize_hazard_type(text), "supercell")
            self.assertIsNone(self.hazard.supercell_semantic_class(text))
            self.assertIsNone(
                self.hazard.supercell_hazard_match_scope(description=text)
            )

    def test_supercell_and_superzelle_are_direct_evidence(self) -> None:
        for text in ("Supercell Warning", "Superzelle erkannt"):
            self.assertEqual(self.hazard.normalize_hazard_type(text), "supercell")
            self.assertEqual(
                self.hazard.supercell_semantic_class(text),
                "official_supercell_alert_event",
            )

    def test_explicit_and_contextual_scopes_are_distinct(self) -> None:
        self.assertEqual(
            self.hazard.supercell_hazard_match_scope(event="Supercell Warning"),
            "explicit_event",
        )
        self.assertEqual(
            self.hazard.supercell_hazard_match_scope(
                event="Tornado Warning",
                description="A dangerous supercell is moving east.",
            ),
            "contextual_text",
        )

    def test_tornado_primary_preserves_additive_supercell_evidence(self) -> None:
        event = "Tornado Warning"
        description = "A dangerous supercell is producing a tornado."
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

    def test_neighbor_hazards_do_not_infer_supercell(self) -> None:
        for event, description in (
            ("Severe Thunderstorm Warning", "Frequent lightning is occurring."),
            ("Tornado Warning", "A tornado is occurring."),
            ("Hail Warning", "Large hail is expected."),
            ("Weather Warning", "A downburst may occur."),
            ("Weather Statement", "Frequent lightning is occurring."),
        ):
            self.assertIsNone(
                self.hazard.supercell_semantic_class(event, description)
            )
            self.assertIsNone(
                self.hazard.supercell_hazard_match_scope(
                    event=event,
                    description=description,
                )
            )

    def test_provider_adapters_match_design_and_revision(self) -> None:
        for source in (self.dwd, self.nws):
            for marker in (
                "supercell_semantic_class(",
                "supercell_hazard_match_scope(",
                '"supercell_semantic_class"',
                '"supercell_match_scope"',
            ):
                self.assertIn(marker, source)
            self.assertNotIn("preferred_provider", source.lower())
            self.assertNotIn("provider_priority", source.lower())
        self.assertRegex(
            self.dwd,
            r'_DWD_PROVIDER_REVISION = "wr-0\.10\.\d+-[a-z0-9_-]+-semantics-\d+"',
        )
        self.assertIn('event_payload.setdefault("alert_stage", "warning")', self.dwd)
        self.assertIn("normalize_alert_stage(event_name, headline)", self.nws)

    def test_consumer_filter_and_preservation_match_design(self) -> None:
        for marker in (
            '"supercell_semantic_classes"',
            '"supercell_match_scopes"',
            '"official_supercell_alert_event"',
            '"supercell_semantic_class"',
            '"supercell_match_scope"',
            "supercell_dimensions",
        ):
            self.assertIn(marker, self.consumer)
        self.assertNotIn(
            'event_filter.get("hazard_types") == {"supercell"}',
            self.consumer,
        )

    def test_existing_additive_semantic_dimensions_are_preserved(self) -> None:
        for marker in (
            '"tornado_semantic_class"',
            '"hazard_match_scope"',
            '"hail_semantic_class"',
            '"hail_match_scope"',
            '"wind_hazard_semantic_class"',
            '"wind_hazard_match_scope"',
            '"supercell_semantic_class"',
            '"supercell_match_scope"',
        ):
            self.assertIn(marker, self.consumer)

    def test_diagnostics_expose_required_supercell_dimensions(self) -> None:
        for marker in (
            '"supercell_semantic_classes"',
            '"supercell_match_scopes"',
            '"alert_stages"',
        ):
            self.assertIn(marker, self.diagnostic)

    def test_public_schemas_are_synchronized(self) -> None:
        request_filters = self.resolve_schema["properties"]["event_filter"]["properties"]
        hazard_event = self.hazard_schema["properties"]["events"]["items"]["properties"]
        hazard_filters = self.hazard_schema["properties"]["event_filter"]["properties"]
        capability_options = _find_event_filter_options(self.capabilities_schema)
        self.assertIsNotNone(capability_options)

        for field in ("supercell_semantic_classes", "supercell_match_scopes"):
            self.assertIn(field, request_filters)
            self.assertIn(field, hazard_filters)
            self.assertIn(field, capability_options)

        for field in ("supercell_semantic_class", "supercell_match_scope"):
            self.assertIn(field, hazard_event)

    def test_thunder_contracts_remain_non_supercell_contracts(self) -> None:
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
        self.assertNotIn(
            "supercell_probability",
            json.dumps([cells, probability]).casefold(),
        )

    def test_forbidden_promotions_are_absent(self) -> None:
        runtime = (self.hazard_source + self.dwd + self.nws + self.consumer).lower()
        for forbidden in (
            "confirmed_supercell_observation_event",
            "observed_or_reported_supercell_event",
            "supercell_probability_forecast",
            "preferred_provider",
            "provider_priority",
        ):
            self.assertNotIn(forbidden, runtime)

    def test_runtime_version_is_exact(self) -> None:
        self.assertRegex(self.const, r'DEV_BUILD_VERSION: Final = "0\.10\.\d+"')
        self.assertRegex(self.const, r'DEV_LOADER_REV: Final = "0\.10-loader-\d+"')

    def test_core_invariants_match_design(self) -> None:
        invariants = set(self.design["invariants"])
        self.assertIn(
            "Mesocyclone aliases are removed from automatic supercell primary normalization.",
            invariants,
        )
        self.assertIn(
            "Supercell semantics are additive and independent of the primary hazard label.",
            invariants,
        )
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)
        self.assertIn("Coverage unknown remains unknown.", invariants)
        self.assertIn("Endpoint reachability is not coverage proof.", invariants)


if __name__ == "__main__":
    unittest.main()
