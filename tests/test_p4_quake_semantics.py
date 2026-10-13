"""Static contract test for P4-QUAKE-20 semantics."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p4_quake_semantics.v1.json"


class P4QuakeSemanticsContractTest(unittest.TestCase):
    """Protect earthquake measurement, impact, role and spatial boundaries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))

    def test_magnitude_is_separate_from_intensity_damage_and_significance(self) -> None:
        magnitude = self.payload["semantic_axes"]["magnitude"]
        self.assertTrue(magnitude["requires_type_context"])
        for value in ("intensity", "damage", "impact", "warning_level", "significance"):
            self.assertIn(value, magnitude["not_equal_to"])

    def test_depth_is_not_severity(self) -> None:
        self.assertTrue(self.payload["semantic_axes"]["depth"]["not_severity"])

    def test_cdi_and_mmi_are_not_magnitude(self) -> None:
        intensity = self.payload["semantic_axes"]["intensity"]
        self.assertTrue(intensity["location_dependent"])
        self.assertTrue(intensity["not_event_magnitude"])
        self.assertFalse(intensity["cdi"]["is_magnitude"])
        self.assertFalse(intensity["mmi"]["is_magnitude"])

    def test_pager_is_impact_not_magnitude_or_local_warning(self) -> None:
        pager = self.payload["semantic_axes"]["pager_alert"]
        self.assertTrue(pager["not_magnitude"])
        self.assertTrue(pager["not_intensity"])
        self.assertTrue(pager["not_official_local_warning_level"])

    def test_significant_is_upstream_selection_not_wr_threshold(self) -> None:
        sig = self.payload["significant_feed"]
        self.assertEqual(sig["source_owner"], "USGS")
        self.assertFalse(sig["direct_weather_router_threshold"])
        self.assertFalse(sig["recomputation_in_weather_router"])
        axis = self.payload["semantic_axes"]["significance"]
        self.assertFalse(axis["weather_router_recomputes"])
        self.assertFalse(axis["weather_router_fixed_threshold"])

    def test_legacy_generic_severity_is_only_presentation_semantics(self) -> None:
        severity = self.payload["current_generic_severity"]
        self.assertEqual(severity["basis"], "weather_router_magnitude_display_band")
        self.assertEqual(severity["semantic_status"], "non_canonical_earthquake_semantics")
        self.assertIn("Modified Mercalli Intensity", severity["must_not_be_interpreted_as"])
        self.assertIn("PAGER impact alert", severity["must_not_be_interpreted_as"])

    def test_tsunami_flag_does_not_promote_to_warning(self) -> None:
        tsunami = self.payload["semantic_axes"]["tsunami_flag"]
        self.assertFalse(tsunami["official_tsunami_warning"])
        self.assertFalse(tsunami["promotes_earthquake_to_tsunami_warning"])

    def test_event_point_is_not_impact_area(self) -> None:
        geometry = self.payload["semantic_axes"]["geometry"]
        self.assertFalse(geometry["event_point_is_impact_area"])
        self.assertFalse(geometry["event_point_is_shaking_footprint"])

    def test_bbox_is_event_filter_but_not_network_coverage(self) -> None:
        bbox = self.payload["spatial_semantics"]["bbox"]
        self.assertTrue(bbox["valid_event_relevance_filter"])
        self.assertFalse(bbox["proves_network_coverage"])

    def test_point_without_radius_does_not_define_nearby_semantics(self) -> None:
        point = self.payload["spatial_semantics"]["point"]
        self.assertFalse(point["exact_coordinate_match_semantically_useful"])
        self.assertFalse(point["current_provider_filtering"])
        self.assertTrue(point["nearby_requires_explicit_distance_or_radius"])

    def test_source_roles_remain_separate(self) -> None:
        roles = self.payload["source_roles"]
        self.assertTrue(roles["usgs_earthquakes"]["dedicated_earthquake_contract"])
        self.assertFalse(roles["usgs_seismic_events"]["merge_with_earthquake"])
        self.assertFalse(roles["gdacs"]["interchangeable_with_usgs_earthquake"])
        self.assertFalse(roles["bmkg_tsunami"]["dedicated_earthquake_contract"])
        self.assertFalse(roles["bmkg_tsunami"]["official_tsunami_warning"])

    def test_non_earthquake_topic_cannot_override_public_contract(self) -> None:
        topic = self.payload["topic_semantics"]
        self.assertTrue(topic["public_contract_is_non_earthquake"])
        self.assertIn("must not override", topic["rule"])

    def test_no_typed_quake_schema_is_claimed_yet(self) -> None:
        schema = self.payload["schema_and_diagnostics_semantics"]
        self.assertFalse(schema["typed_earthquake_object_currently_present"])
        self.assertTrue(schema["generic_parameters_currently_used"])
        self.assertFalse(schema["quake_specific_routing_summary_currently_present"])

    def test_core_invariants_are_explicit(self) -> None:
        invariants = set(self.payload["invariants"])
        for expected in (
            "Magnitude is not intensity.",
            "PAGER alert is an impact estimate and not the earthquake magnitude.",
            "USGS significant does not imply a WeatherRouter-defined fixed magnitude threshold.",
            "Earthquake is not automatically tsunami.",
            "USGS tsunami_flag is not an official tsunami warning.",
            "A point request without an explicit radius does not define a valid nearby-earthquake distance.",
            "Endpoint reachability is not coverage proof.",
            "GDACS earthquake remains disaster awareness and is not interchangeable with primary seismic observation.",
            "USGS non-earthquake seismic remains separate from earthquake.",
            "Provider ID is not a scoring axis.",
            "Profiles remain deny-only.",
        ):
            self.assertIn(expected, invariants)


if __name__ == "__main__":
    unittest.main()
