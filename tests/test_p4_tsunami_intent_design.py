"""Static contract test for the P4-TSUNAMI-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p4_tsunami_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"


class P4TsunamiIntentDesignContractTest(unittest.TestCase):
    """Protect tsunami intent design without public-contract sprawl."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))

    def test_no_new_public_capability_is_designed(self) -> None:
        self.assertEqual(self.design["public_capabilities_added"], 0)
        self.assertEqual(
            self.design["public_capability_count_before"],
            self.design["public_capability_count_after"],
        )
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)

    def test_tsunami_semantics_is_structured_additive_event_field(self) -> None:
        semantics = self.design["event_semantics"]
        self.assertEqual(semantics["field"], "tsunami_semantics")
        self.assertEqual(semantics["required_fields"], ["semantic_class"])
        self.assertIn("alert_stage", semantics["optional_fields"])
        self.assertIn("wave_evidence", semantics["optional_fields"])

    def test_source_roles_have_distinct_semantic_classes(self) -> None:
        classes = set(self.design["event_semantics"]["semantic_classes"])
        self.assertEqual(
            classes,
            {
                "official_tsunami_warning_event",
                "tsunami_observation_event",
                "tsunami_potential_indicator_event",
                "disaster_awareness_tsunami_event",
            },
        )

    def test_generic_alert_stage_is_not_expanded(self) -> None:
        self.assertFalse(
            self.design["generic_alert_stage"]["extended_for_tsunami"]
        )
        self.assertIn("advisory", self.design["event_semantics"]["alert_stages"])
        self.assertIn("marine_warning", self.design["event_semantics"]["alert_stages"])

    def test_jma_observation_mapping_is_corrected(self) -> None:
        target = self.design["mappings"]["jma_observation"]["capability_map_target"]
        self.assertEqual(target["observation_kind"], "observation")
        self.assertEqual(target["measurement_method"], "tsunami_observation_feed")
        self.assertEqual(target["source_class"], "observation")

    def test_bmkg_potential_mapping_is_not_warning_semantics(self) -> None:
        target = self.design["mappings"]["bmkg_potential"]["capability_map_target"]
        self.assertEqual(target["data_origin"], "seismic_network")
        self.assertEqual(target["measurement_method"], "seismic_event_catalog")
        self.assertEqual(target["observation_kind"], "observation")
        self.assertEqual(target["source_class"], "event_indicator")
        self.assertEqual(target["hazard_type"], "tsunami_potential")

    def test_gdacs_remains_disaster_awareness(self) -> None:
        gdacs = self.design["mappings"]["gdacs"]
        self.assertEqual(
            gdacs["semantic_class"],
            "disaster_awareness_tsunami_event",
        )
        self.assertTrue(gdacs["preserve_disaster_awareness_role"])

    def test_filter_capability_gating_is_explicit(self) -> None:
        filters = self.design["event_filter_additions"]
        self.assertEqual(
            filters["tsunami_alert_stages"]["compatible_public_capabilities"],
            ["natural_hazards.tsunami.warnings"],
        )
        self.assertEqual(
            filters["tsunami_semantic_classes"]["filter_path"],
            "tsunami_semantics.semantic_class",
        )

    def test_unknown_geometry_is_not_outside_coverage(self) -> None:
        spatial = self.design["spatial_design"]["point_bbox"]
        self.assertFalse(spatial["missing_geometry_is_outside_coverage"])
        self.assertEqual(
            spatial["missing_geometry_event_behavior"],
            "preserve_with_spatial_relevance_unknown_geometry",
        )
        self.assertFalse(spatial["provider_identity_as_geometry"])
        self.assertFalse(spatial["region_text_as_geometry"])
        self.assertFalse(
            spatial["empty_explicit_geometry_matches_with_unknown_events_means_no_hazard"]
        )

    def test_bmkg_epicenter_is_not_tsunami_impact_area(self) -> None:
        self.assertFalse(
            self.design["mappings"]["bmkg_potential"]["epicenter_is_tsunami_impact_area"]
        )

    def test_runtime_version_is_planned(self) -> None:
        versions = self.design["versions"]
        self.assertEqual(versions["planned_build_version"], "0.10.129")
        self.assertEqual(versions["planned_loader_revision"], "0.10-loader-132")

    def test_core_invariants_are_explicit(self) -> None:
        invariants = set(self.design["invariants"])
        for expected in (
            "No new public capability.",
            "Generic alert_stage is not expanded for tsunami-specific stages.",
            "BMKG potential remains an event indicator and not a warning.",
            "GDACS remains disaster awareness.",
            "Missing geometry is not outside_coverage.",
            "Provider ID is not a scoring axis.",
            "Profiles remain deny-only.",
        ):
            self.assertIn(expected, invariants)


if __name__ == "__main__":
    unittest.main()
