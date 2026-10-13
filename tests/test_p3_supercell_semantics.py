"""Static contract test for P3-SUPERCELL-20 semantics."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p3_supercell_semantics.v1.json"


class P3SupercellSemanticsContractTest(unittest.TestCase):
    """Protect the semantic separation of supercell and rotation evidence."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))

    def test_official_supercell_alert_uses_existing_warning_transport(self) -> None:
        semantic = self.payload["official_supercell_alert"]
        self.assertEqual(semantic["semantic_class"], "official_supercell_alert_event")
        self.assertEqual(semantic["transport"], "weather.warning.official")
        self.assertEqual(semantic["resource_type"], "hazard_feed")
        self.assertEqual(
            semantic["sufficient_text_evidence"],
            ["supercell", "superzelle"],
        )

    def test_mesocyclone_is_not_automatic_supercell(self) -> None:
        meso = self.payload["mesocyclone_semantics"]
        self.assertEqual(meso["semantic_class"], "mesocyclone_rotation_signature")
        self.assertEqual(meso["status"], "not_implemented")
        self.assertFalse(meso["mesocyclone_is_automatic_supercell"])
        self.assertFalse(meso["mesocyclone_is_visual_observation"])
        self.assertFalse(meso["mesocyclone_is_confirmed_supercell"])
        self.assertTrue(meso["current_runtime_maps_mesocyclone_to_primary_supercell"])

    def test_primary_hazard_type_is_not_complete_semantics(self) -> None:
        primary = self.payload["primary_hazard_semantics"]
        self.assertEqual(
            primary["relevant_order"],
            [
                "waterspout",
                "tornado",
                "supercell",
                "downburst",
                "severe_thunderstorm",
                "hail",
            ],
        )
        self.assertFalse(primary["primary_label_is_complete_semantics"])
        self.assertFalse(primary["runtime_change_in_p3_supercell_20"])

    def test_explicit_and_contextual_supercell_evidence_are_distinct(self) -> None:
        scopes = self.payload["supercell_evidence_scope"]
        self.assertEqual(scopes["explicit_event"]["fields"], ["event", "headline"])
        self.assertEqual(
            scopes["contextual_text"]["fields"],
            ["description", "instruction"],
        )
        self.assertTrue(scopes["both_support_official_supercell_alert_event"])
        self.assertTrue(scopes["neither_implies_confirmed_observation"])
        self.assertTrue(scopes["explicit_precedence"])

    def test_alert_stage_is_reused_without_invention(self) -> None:
        stage = self.payload["alert_stage"]
        self.assertTrue(stage["reuse_existing_field"])
        self.assertEqual(stage["missing_stage"], "must_not_be_invented")
        self.assertEqual(
            stage["allowed"],
            ["warning", "watch", "outlook", "statement", "unspecified"],
        )

    def test_thunder_contracts_remain_separate(self) -> None:
        related = self.payload["related_contracts"]
        self.assertFalse(
            related["weather.convection.thunderstorm_cells"]["is_supercell_classification"]
        )
        self.assertFalse(
            related["weather.point.thunder_probability"]["is_supercell_probability"]
        )

    def test_observation_rotation_and_probability_classes_are_not_implemented(self) -> None:
        classes = self.payload["observation_and_forecast_classes"]
        self.assertEqual(classes["confirmed_supercell_observation_event"], "not_implemented")
        self.assertEqual(classes["observed_or_reported_supercell_event"], "not_implemented")
        self.assertEqual(classes["mesocyclone_rotation_signature"], "not_implemented")
        self.assertEqual(classes["supercell_probability_forecast"], "not_implemented")

    def test_neighbor_hazards_are_not_automatic_supercell(self) -> None:
        overlap = self.payload["overlap_rules"]
        for key in (
            "severe_thunderstorm_is_automatically_supercell",
            "tornado_is_automatically_supercell",
            "hail_is_automatically_supercell",
            "downburst_is_automatically_supercell",
            "lightning_is_automatically_supercell",
        ):
            self.assertFalse(overlap[key])
        self.assertTrue(
            overlap[
                "real_supercell_text_can_add_supercell_semantics_independent_of_primary_hazard_type"
            ]
        )

    def test_providers_require_real_event_evidence(self) -> None:
        for provider in self.payload["provider_semantics"].values():
            self.assertFalse(provider["registry_topic_supercell"])
            self.assertFalse(provider["dedicated_supercell_capability"])
            self.assertTrue(
                provider[
                    "broad_official_supercell_alert_supported_only_when_real_event_text_contains_supercell_evidence"
                ]
            )

    def test_core_invariants_remain_explicit(self) -> None:
        invariants = set(self.payload["invariants"])
        self.assertIn("Mesocyclone is not automatically supercell.", invariants)
        self.assertIn("Thunderstorm cell is not automatically supercell.", invariants)
        self.assertIn("Tornado is not automatically supercell.", invariants)
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)


if __name__ == "__main__":
    unittest.main()
