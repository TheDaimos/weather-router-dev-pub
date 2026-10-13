"""Static contract test for the P3-SUPERCELL-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p3_supercell_intent_design.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"


class P3SupercellIntentDesignContractTest(unittest.TestCase):
    """Protect the provider-neutral P3-SUPERCELL-30 design."""

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
        ids = self.mapping["public_capabilities"]
        self.assertFalse(any("supercell" in item.casefold() for item in ids))

    def test_existing_warning_transport_remains_aggregate(self) -> None:
        transport = self.design["public_transport"]
        self.assertEqual(transport["id"], "weather.warning.official")
        self.assertEqual(transport["strategy"], "aggregate")
        self.assertEqual(
            transport["candidates"],
            [
                "dwd/official_weather_warnings",
                "noaa_nws/official_weather_alerts",
            ],
        )

    def test_pattern_order_is_preserved_but_mesocyclone_aliases_are_removed(self) -> None:
        primary = self.design["primary_hazard_type"]
        self.assertFalse(primary["reorder_patterns"])
        self.assertTrue(primary["remove_mesocyclone_aliases_from_supercell"])
        self.assertEqual(
            primary["supercell_keywords_after"],
            ["supercell", "superzelle"],
        )
        self.assertNotIn("mesocyclone", primary["supercell_keywords_after"])
        self.assertNotIn("mesozyklone", primary["supercell_keywords_after"])

    def test_supercell_semantics_are_additive(self) -> None:
        field = self.design["additive_event_fields"]["supercell_semantic_class"]
        self.assertEqual(field["values"], ["official_supercell_alert_event"])
        self.assertTrue(field["independent_of_primary_hazard_type"])

    def test_match_scope_distinguishes_explicit_and_contextual(self) -> None:
        field = self.design["additive_event_fields"]["supercell_match_scope"]
        self.assertEqual(set(field["values"]), {"explicit_event", "contextual_text"})
        self.assertEqual(field["explicit_fields"], ["event", "headline"])
        self.assertEqual(field["contextual_fields"], ["description", "instruction"])
        self.assertTrue(field["explicit_precedence"])

    def test_mesocyclone_is_excluded_from_supercell_evidence(self) -> None:
        evidence = self.design["evidence"]
        self.assertEqual(evidence["official_supercell"], ["supercell", "superzelle"])
        self.assertFalse(evidence["mesocyclone_is_supercell_evidence"])
        self.assertEqual(
            set(evidence["mesocyclone_keywords_kept_outside_supercell_class"]),
            {"mesocyclone", "mesozyklone"},
        )

    def test_specialized_filter_does_not_require_primary_supercell_label(self) -> None:
        filters = self.design["event_filter_additions"]
        self.assertEqual(
            filters["supercell_semantic_classes"],
            ["official_supercell_alert_event"],
        )
        self.assertTrue(
            filters["specialized_filter_does_not_require_primary_supercell_hazard_type"]
        )
        self.assertTrue(filters["capability_gate_requires_hazard_type_supercell"])

    def test_related_thunder_contracts_are_preserved(self) -> None:
        unchanged = set(self.design["related_contracts_unchanged"])
        self.assertEqual(
            unchanged,
            {
                "weather.convection.thunderstorm_cells",
                "weather.point.thunder_probability",
            },
        )

    def test_rotation_observation_and_probability_promotions_are_excluded(self) -> None:
        excluded = set(self.design["excluded"])
        self.assertIn("mesocyclone_rotation_signature_runtime_field", excluded)
        self.assertIn("confirmed_supercell_observation_event", excluded)
        self.assertIn("supercell_probability_forecast", excluded)
        self.assertIn("thunderstorm_cell_to_supercell_inference", excluded)
        self.assertIn("thunder_probability_to_supercell_inference", excluded)

    def test_core_routing_invariants_remain_explicit(self) -> None:
        invariants = set(self.design["invariants"])
        self.assertIn("Mesocyclone is not automatically supercell.", invariants)
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)
        self.assertIn("Coverage unknown remains unknown.", invariants)


if __name__ == "__main__":
    unittest.main()
