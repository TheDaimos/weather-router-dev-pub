"""Static contract test for P4-FLOOD-20 semantics."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p4_flood_semantics.v1.json"


class P4FloodSemanticsContractTest(unittest.TestCase):
    """Protect flood subtype and source-class semantic boundaries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))

    def test_all_official_flood_event_classes_are_distinct(self) -> None:
        classes = self.payload["official_event_classes"]
        self.assertEqual(len(classes), 8)
        self.assertEqual(len(set(classes)), 8)
        self.assertIn("official_flood_alert_event", classes)
        self.assertIn("official_flash_flood_alert_event", classes)
        self.assertIn("official_glof_alert_event", classes)
        self.assertIn("official_ice_jam_flood_alert_event", classes)

    def test_generic_flood_is_lower_specificity_fallback(self) -> None:
        fallback = self.payload["generic_fallback"]
        self.assertEqual(fallback["class"], "official_flood_alert_event")
        self.assertTrue(fallback["lower_specificity_than_named_subtypes"])

    def test_cause_and_manifestation_can_coexist(self) -> None:
        rule = self.payload["multi_hazard_rule"]
        self.assertTrue(rule["classes_are_not_mutually_exclusive"])
        self.assertTrue(rule["preserve_all_supported_evidence"])
        self.assertTrue(rule["primary_hazard_type_is_not_complete_semantics"])

    def test_flash_flood_is_not_synonym_for_dam_or_levee_failure(self) -> None:
        sub = self.payload["subtype_semantics"]
        self.assertTrue(sub["flash_flood"]["cause_is_not_same_as_manifestation"])
        self.assertTrue(sub["dam_failure"]["not_synonym_for_flash_flood"])
        self.assertTrue(sub["levee_failure"]["not_synonym_for_flash_flood"])

    def test_surface_water_flood_is_distinct(self) -> None:
        surface = self.payload["subtype_semantics"]["surface_water_flood"]
        self.assertTrue(surface["not_automatic_river_flood"])

    def test_heavy_rain_is_precursor_not_automatic_flood(self) -> None:
        rain = self.payload["heavy_rain"]
        self.assertFalse(rain["is_automatic_flood"])
        self.assertFalse(rain["is_automatic_flash_flood"])
        self.assertFalse(rain["is_part_of_dedicated_flood_warning_contract"])

    def test_glofas_is_never_official_warning_semantics(self) -> None:
        model = self.payload["source_classes"]["glofas_model"]
        self.assertFalse(model["eligible_for_official_flood_event_classes"])
        self.assertEqual(model["data_origin"], "model")
        self.assertEqual(model["measurement_method"], "hydrological_model")

    def test_official_warning_sources_can_carry_flood_classes(self) -> None:
        warning = self.payload["source_classes"]["official_warning"]
        self.assertTrue(warning["eligible_for_official_flood_event_classes"])
        self.assertIn(
            "nina_flood/flood_information_germany",
            warning["examples"],
        )

    def test_public_warning_intents_are_complementary_not_interchangeable(self) -> None:
        relation = self.payload["contract_relationship"]
        self.assertEqual(
            relation["weather.warning.official_and_natural_hazards.flood.warning"],
            "complementary_not_interchangeable",
        )

    def test_nina_unreachable_semantics_are_not_synthesized(self) -> None:
        gap = self.payload["nina_gap"]
        self.assertEqual(
            gap["declared_but_not_directly_reachable"],
            ["glacial_lake_outburst_flood", "ice_jam_flood"],
        )
        self.assertIn("must not be synthesized", gap["semantic_rule"])

    def test_alert_stage_only_reused_for_official_warning_events(self) -> None:
        stage = self.payload["alert_stage"]
        self.assertTrue(stage["reuse_existing_field_for_official_warning_events"])
        self.assertEqual(stage["missing_stage"], "must_not_be_invented")

    def test_core_invariants_are_explicit(self) -> None:
        invariants = set(self.payload["invariants"])
        self.assertIn("Heavy rain is not automatically flood or flash flood.", invariants)
        self.assertIn("GloFAS model output is not an official warning.", invariants)
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)


if __name__ == "__main__":
    unittest.main()
