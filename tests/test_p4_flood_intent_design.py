"""Static contract test for the P4-FLOOD-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p4_flood_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"


class P4FloodIntentDesignContractTest(unittest.TestCase):
    """Protect multi-valued flood semantics and source separation."""

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

    def test_flood_semantics_are_multi_valued_and_paired(self) -> None:
        semantics = self.design["event_semantics"]
        self.assertEqual(semantics["field"], "flood_semantics")
        self.assertEqual(semantics["shape"], "array_of_objects")
        self.assertTrue(semantics["allow_multiple_classes_per_event"])
        self.assertTrue(semantics["preserve_class_scope_pairing"])
        self.assertTrue(semantics["independent_of_primary_hazard_type"])

    def test_all_eight_semantic_classes_are_designed(self) -> None:
        classes = self.design["event_semantics"]["semantic_classes"]
        self.assertEqual(len(classes), 8)
        self.assertEqual(len(set(classes)), 8)

    def test_generic_flood_is_not_substring_inference(self) -> None:
        rule = self.design["generic_flood_rule"]
        self.assertTrue(rule["do_not_infer_from_specific_compound_only"])
        self.assertIn("flash flood", rule["examples_not_generic_by_substring_alone"])
        self.assertIn("ice jam flood", rule["examples_not_generic_by_substring_alone"])

    def test_nina_synthetic_label_is_not_evidence(self) -> None:
        nina = self.design["provider_design"]["nina_flood"]
        self.assertTrue(nina["attach_flood_semantics_from_real_headline_only"])
        self.assertTrue(nina["do_not_use_synthetic_event_label_as_evidence"])

    def test_nina_glof_and_ice_jam_are_real_text_patterns(self) -> None:
        fix = self.design["nina_reachability_fix"]
        self.assertIn("glof", fix["add_real_title_patterns"]["glacial_lake_outburst_flood"])
        self.assertIn("eisstau", fix["add_real_title_patterns"]["ice_jam_flood"])
        self.assertTrue(fix["no_synthetic_fallback_to_specific_subtype"])

    def test_event_filters_use_explicit_capability_gate(self) -> None:
        filters = self.design["event_filter_additions"]
        self.assertEqual(
            set(filters["compatible_public_capabilities"]),
            {
                "weather.warning.official",
                "natural_hazards.flood.warning",
                "civil_protection.warning.official",
            },
        )
        self.assertTrue(filters["not_enabled_for_glofas_rasters"])
        self.assertTrue(filters["not_enabled_for_seismic_non_earthquake_events"])
        self.assertTrue(filters["does_not_require_primary_flood_hazard_type"])

    def test_glofas_contracts_are_not_changed(self) -> None:
        self.assertFalse(self.design["glofas"]["public_contracts_changed"])
        self.assertTrue(self.design["glofas"]["model_products_stay_separate"])
        self.assertFalse(self.design["glofas"]["official_warning_inference"])

    def test_heavy_rain_is_not_promoted(self) -> None:
        rain = self.design["heavy_rain"]
        self.assertFalse(rain["runtime_change"])
        self.assertFalse(rain["automatic_flood_semantics"])

    def test_core_invariants_are_explicit(self) -> None:
        invariants = set(self.design["invariants"])
        self.assertIn("Class-to-match-scope pairing is preserved.", invariants)
        self.assertIn("Heavy rain is not automatically flood.", invariants)
        self.assertIn("GloFAS model output is not official-warning semantics.", invariants)
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)


if __name__ == "__main__":
    unittest.main()
