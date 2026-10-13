"""Static contract test for the P4-QUAKE-10 inventory."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "p4_quake_inventory.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
REGISTRY_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "registry.json"
USGS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "usgs_earthquakes.py"
SEISMIC_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "usgs_seismic_events.py"
GDACS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "gdacs.py"
BMKG_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "bmkg_tsunami.py"
CONSUMER_API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
HAZARD_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "resources" / "hazard_feed.schema.json"
DIAGNOSTIC_CORE_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"


class P4QuakeInventoryContractTest(unittest.TestCase):
    """Keep P4-QUAKE-10 tied to the current standard-core contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["providers"]
        cls.usgs = USGS_PATH.read_text(encoding="utf-8")
        cls.seismic = SEISMIC_PATH.read_text(encoding="utf-8")
        cls.gdacs = GDACS_PATH.read_text(encoding="utf-8")
        cls.bmkg = BMKG_PATH.read_text(encoding="utf-8")
        cls.consumer_api = CONSUMER_API_PATH.read_text(encoding="utf-8")
        cls.hazard_schema = json.loads(HAZARD_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.diagnostic_core = DIAGNOSTIC_CORE_PATH.read_text(encoding="utf-8")

    def _candidates_for(self, public_id: str) -> set[str]:
        result: set[str] = set()
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    result.add(f"{provider_id}/{capability_id}")
        return result

    def test_dedicated_earthquake_public_contracts_are_separate(self) -> None:
        self.assertEqual(
            self._candidates_for("natural_hazards.earthquake.events"),
            {"usgs_earthquakes/earthquakes_past_day"},
        )
        self.assertEqual(
            self._candidates_for("natural_hazards.earthquake.significant_events"),
            {"usgs_earthquakes/significant_earthquakes_past_month"},
        )
        for public_id in (
            "natural_hazards.earthquake.events",
            "natural_hazards.earthquake.significant_events",
        ):
            contract = self.mapping["public_capabilities"][public_id]
            self.assertEqual(contract["family"], "earthquake")
            self.assertEqual(contract["hazard_types"], ["earthquake"])
            self.assertEqual(contract["resource_types"], ["hazard_feed"])

    def test_usgs_earthquake_inventory_records_original_revision_and_feeds(self) -> None:
        self.assertEqual(
            self.inventory["providers"]["usgs_earthquakes"]["revision"],
            "wr-0.10.40-usgs-earthquakes-1",
        )
        self.assertIn("summary/all_day.geojson", self.usgs)
        self.assertIn("summary/significant_month.geojson", self.usgs)
        self.assertIn('event_type != "earthquake"', self.usgs)

    def test_usgs_preserves_quake_measurement_and_context_fields(self) -> None:
        for field in (
            '"magnitude"', '"magnitude_type"', '"depth_km"', '"felt_reports"',
            '"community_intensity_cdi"', '"instrumental_intensity_mmi"',
            '"pager_alert"', '"significance"', '"tsunami_flag"', '"usgs_status"',
            '"network"', '"code"',
        ):
            self.assertIn(field, self.usgs)

    def test_magnitude_severity_is_explicitly_a_display_band(self) -> None:
        self.assertIn("weather_router_magnitude_display_band", self.usgs)
        self.assertIn("magnitude >= 7.0", self.usgs)
        self.assertIn("magnitude >= 6.0", self.usgs)
        self.assertIn("magnitude >= 5.0", self.usgs)
        mapping = self.inventory["providers"]["usgs_earthquakes"]["magnitude_display_mapping"]
        self.assertFalse(mapping["semantic_warning_level"])
        self.assertFalse(mapping["intensity_or_damage_scale"])

    def test_usgs_bbox_exists_but_point_arguments_are_ignored(self) -> None:
        self.assertIn("del latitude, longitude", self.usgs)
        self.assertIn("def _point_in_bbox(", self.usgs)
        finding = self.inventory["filtering"]["point_context_gap"]
        self.assertIn("ignore latitude/longitude", finding)
        self.assertIn("if candidate.public_id in _TSUNAMI_SEMANTIC_PUBLIC_IDS:", self.consumer_api)
        self.assertNotIn('"natural_hazards.earthquake.events"', self.consumer_api.split("_TSUNAMI_SEMANTIC_PUBLIC_IDS", 1)[1].split(")", 1)[0])

    def test_coverage_contract_does_not_use_endpoint_reachability(self) -> None:
        coverage = self.mapping["capability_coverage_semantics"]["providers"]
        for provider_id, capability_id in (
            ("usgs_earthquakes", "earthquakes_past_day"),
            ("usgs_earthquakes", "significant_earthquakes_past_month"),
            ("usgs_seismic_events", "non_earthquake_seismic_past_day"),
            ("gdacs", "global_disaster_alerts_7d"),
            ("bmkg_tsunami", "tsunami_potential_earthquake"),
        ):
            item = coverage[provider_id][capability_id]
            self.assertEqual(item["coverage_scope"], "dynamic")
            self.assertEqual(item["coverage_evidence"], "runtime_event_geometry")
            self.assertEqual(item["routing_authority"], "context_filter")
            self.assertFalse(item["endpoint_reachability_is_coverage"])

    def test_provider_defaults_are_inventory_truth(self) -> None:
        entries = {item["module"]: item for item in self.registry}
        self.assertTrue(entries["usgs_earthquakes"]["default_enabled"])
        self.assertFalse(entries["usgs_seismic_events"]["default_enabled"])
        self.assertFalse(entries["gdacs"]["default_enabled"])
        self.assertTrue(entries["bmkg_tsunami"]["default_enabled"])

    def test_non_earthquake_seismic_path_remains_separate(self) -> None:
        self.assertEqual(
            self._candidates_for("natural_hazards.seismic_non_earthquake.events"),
            {"usgs_seismic_events/non_earthquake_seismic_past_day"},
        )
        self.assertIn('event_type.casefold() == "earthquake"', self.seismic)
        self.assertIn('"usgs_event_type_filter": "type != earthquake"', self.seismic)
        self.assertFalse(
            self.inventory["public_paths"]["seismic_non_earthquake"][
                "interchangeable_with_earthquake_contract"
            ]
        )

    def test_gdacs_eq_stays_disaster_awareness(self) -> None:
        self.assertIn('"EQ": "earthquake"', self.gdacs)
        self.assertIn('"source_class": "disaster_awareness"', self.gdacs)
        self.assertIn('"aggregator": True', self.gdacs)
        self.assertIn('"primary_warning_authority": False', self.gdacs)
        path = self.inventory["public_paths"]["disaster_awareness"]
        self.assertTrue(path["aggregator"])
        self.assertFalse(path["primary_warning_authority"])

    def test_bmkg_earthquake_data_stays_tsunami_potential(self) -> None:
        self.assertEqual(
            self._candidates_for("natural_hazards.tsunami.potential"),
            {"bmkg_tsunami/tsunami_potential_earthquake"},
        )
        self.assertIn('"hazard_type": "tsunami_potential"', self.bmkg)
        self.assertIn('"earthquake_epicenter": geometry', self.bmkg)
        self.assertIn('"geometry": None', self.bmkg)
        self.assertFalse(self.inventory["public_paths"]["tsunami_potential"]["official_tsunami_warning"])

    def test_significant_feed_has_no_weather_router_fixed_threshold_contract(self) -> None:
        path = self.inventory["public_paths"]["significant_events"]
        self.assertFalse(path["fixed_magnitude_threshold_encoded_in_weather_router"])
        self.assertEqual(path["significant_selection_owner"], "USGS upstream summary feed")

    def test_feed_overlap_is_recorded_without_deduplication(self) -> None:
        overlap = self.inventory["feed_overlap"]["usgs_all_day_and_significant_month"]
        self.assertTrue(overlap["possible"])
        self.assertFalse(overlap["deduplication_currently_implemented"])
        self.assertTrue(overlap["inventory_only_no_deduplication_decision"])

    def test_inventory_records_pre_quake_typed_schema_state(self) -> None:
        event_props = self.hazard_schema["properties"]["events"]["items"]["properties"]
        self.assertEqual(event_props["parameters"], {"type": "object"})
        self.assertFalse(
            self.inventory["schema_inventory"]["quake_specific_semantics_object_present"]
        )
        # P4-QUAKE-10 records the historical inventory state. Later approved phases
        # may add an additive typed object without invalidating that inventory.

    def test_routing_diagnostic_has_no_quake_specific_summary_today(self) -> None:
        self.assertIn('"geometry_count"', self.diagnostic_core)
        self.assertIn('"severities"', self.diagnostic_core)
        self.assertNotIn('"earthquake_magnitudes"', self.diagnostic_core)
        self.assertFalse(
            self.inventory["schema_inventory"]["diagnostic_quake_specific_summary_present"]
        )

    def test_inventory_hard_boundaries_are_explicit(self) -> None:
        invariants = set(self.inventory["invariants"])
        for expected in (
            "USGS significant does not imply a WeatherRouter-defined fixed magnitude threshold.",
            "Earthquake is not automatically tsunami.",
            "USGS tsunami_flag is metadata and not an official tsunami warning.",
            "GDACS earthquake remains disaster awareness and is not an interchangeable primary observation.",
            "USGS non-earthquake seismic remains separate from earthquake.",
            "Endpoint reachability is not coverage proof.",
            "Provider ID is not a scoring axis.",
            "Profiles remain deny-only.",
            "No cross-provider or cross-feed deduplication is introduced in P4-QUAKE-10.",
        ):
            self.assertIn(expected, invariants)


if __name__ == "__main__":
    unittest.main()
