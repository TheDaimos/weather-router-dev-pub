"""Static contract test for the P3-HAIL-20 semantic classification."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p3_hail_semantics.v1.json"


class P3HailSemanticsContractTest(unittest.TestCase):
    """Protect the semantic separation of hail-related information."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))

    def test_broad_official_hail_alert_class_uses_existing_warning_transport(self) -> None:
        semantic = self.payload["broad_semantic_class"]["official_hail_alert_event"]
        self.assertEqual(semantic["transport"], "weather.warning.official")
        self.assertEqual(semantic["resource_type"], "hazard_feed")
        self.assertEqual(semantic["observation_kind"], "warning_event")
        self.assertEqual(
            semantic["status"],
            "defined_for_design_not_yet_runtime_field",
        )

    def test_primary_hazard_type_is_not_complete_hail_semantics(self) -> None:
        primary = self.payload["primary_hazard_type"]
        self.assertEqual(primary["id"], "hail")
        self.assertEqual(primary["keywords"], ["hail", "hagel"])
        missing = set(primary["does_not_guarantee"])
        self.assertIn("observed_hail", missing)
        self.assertIn("hail_size", missing)
        self.assertIn("radar_hail_signature", missing)
        self.assertIn("hail_probability", missing)

    def test_single_label_precedence_problem_is_explicit(self) -> None:
        problem = self.payload["multi_hazard_problem"]
        self.assertEqual(problem["current_model"], "single_label_first_match")
        self.assertTrue(problem["severe_thunderstorm_precedes_hail"])
        self.assertFalse(problem["runtime_change_in_p3_hail_20"])
        self.assertIn("severe_thunderstorm", problem["consequence"])

    def test_explicit_and_contextual_hail_evidence_are_distinct(self) -> None:
        scopes = self.payload["hail_evidence_scope"]
        self.assertEqual(scopes["explicit_event"]["fields"], ["event", "headline"])
        self.assertEqual(
            scopes["contextual_text"]["fields"],
            ["description", "instruction"],
        )
        self.assertTrue(scopes["both_support_broad_official_hail_alert"])
        self.assertTrue(scopes["neither_implies_observed_hail"])

    def test_observed_hail_is_not_inferred_from_warning_or_radar_metadata(self) -> None:
        observed = self.payload["observed_hail"]
        self.assertEqual(observed["status"], "not_implemented")
        insufficient = set(observed["insufficient_alone"])
        self.assertIn("hazard_type_hail", insufficient)
        self.assertIn("hail_warning_text", insufficient)
        self.assertIn("cap_certainty", insufficient)
        self.assertIn("radar_hail_signature", insufficient)

    def test_hail_size_is_numeric_and_not_severity(self) -> None:
        size = self.payload["hail_size"]
        self.assertEqual(size["status"], "not_implemented")
        self.assertFalse(size["severity_is_size"])
        self.assertIn("numeric_value", size["required_future_contract"])
        self.assertIn("canonical_length_unit_mm", size["required_future_contract"])

    def test_radar_hail_signature_is_separate(self) -> None:
        radar = self.payload["radar_hail"]
        self.assertEqual(radar["status"], "not_implemented")
        self.assertFalse(radar["observed_hail_equivalent"])
        self.assertFalse(radar["official_warning_equivalent"])
        self.assertFalse(radar["radar_reflectivity_alone_is_hail"])

    def test_hail_probability_is_separate(self) -> None:
        probability = self.payload["probability"]
        self.assertEqual(probability["status"], "not_implemented")
        self.assertFalse(probability["thunder_probability_is_hail_probability"])
        self.assertIn(
            "canonical_percent_unit",
            probability["required_future_contract"],
        )

    def test_provider_descriptions_do_not_prove_active_hail_event(self) -> None:
        for provider in self.payload["provider_semantics"].values():
            self.assertTrue(provider["registry_topic_hail"])
            self.assertTrue(provider["capability_explicit_hail_description"])
            self.assertFalse(provider["dedicated_hail_capability"])

    def test_core_invariants_remain_explicit(self) -> None:
        invariants = set(self.payload["invariants"])
        self.assertIn("Official hail alert is not observed hail.", invariants)
        self.assertIn("Severe thunderstorm is not automatically hail.", invariants)
        self.assertIn("Severity is not hail size.", invariants)
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)


if __name__ == "__main__":
    unittest.main()
