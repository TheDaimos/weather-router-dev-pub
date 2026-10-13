"""Static contract test for the P3-TORNADO-20 semantic classification."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p3_tornado_semantics.v1.json"


class P3TornadoSemanticsContractTest(unittest.TestCase):
    """Protect the semantic separation of tornado-related information."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))

    def test_current_implemented_classes_are_only_official_alert_events(self) -> None:
        classes = self.payload["implemented_semantic_classes"]
        self.assertEqual(
            set(classes),
            {"official_tornado_alert_event", "official_waterspout_alert_event"},
        )
        self.assertEqual(
            classes["official_tornado_alert_event"]["transport"],
            "weather.warning.official",
        )
        self.assertEqual(
            classes["official_waterspout_alert_event"]["hazard_type"],
            "waterspout",
        )

    def test_confirmed_tornado_is_not_inferred_from_warning_metadata(self) -> None:
        semantics = self.payload["confirmed_event_semantics"]
        self.assertEqual(semantics["status"], "not_implemented")
        insufficient = set(semantics["insufficient_alone"])
        self.assertIn("hazard_type_tornado", insufficient)
        self.assertIn("tornado_warning_event_name", insufficient)
        self.assertIn("cap_certainty", insufficient)
        self.assertIn("warning_polygon", insufficient)
        self.assertIn("radar_rotation", insufficient)

    def test_watch_warning_outlook_statement_are_distinct(self) -> None:
        stages = self.payload["alert_stage_semantics"]
        self.assertEqual(stages["current_runtime_normalization"], "not_distinct")
        self.assertEqual(stages["missing_stage"], "must_not_be_invented")
        for name in ("warning", "watch", "outlook", "statement"):
            self.assertIn(name, stages)

    def test_waterspout_remains_separate(self) -> None:
        normalization = self.payload["normalization"]
        self.assertTrue(normalization["waterspout_remains_distinct"])
        self.assertEqual(
            normalization["waterspout_keywords"],
            ["waterspout", "wasserhose"],
        )

    def test_radar_rotation_never_equals_confirmed_tornado(self) -> None:
        rotation = self.payload["radar_rotation"]
        self.assertEqual(rotation["status"], "not_implemented")
        self.assertFalse(rotation["confirmed_tornado_equivalent"])
        self.assertFalse(rotation["thunderstorm_cell_equivalent"])
        self.assertFalse(
            rotation["supercell_or_mesocyclone_equivalent_to_confirmed_tornado"]
        )

    def test_tornado_probability_is_separate_and_not_implemented(self) -> None:
        probability = self.payload["probability"]
        self.assertEqual(probability["status"], "not_implemented")
        self.assertFalse(probability["thunder_probability_is_tornado_probability"])
        self.assertIn("canonical_percent_unit", probability["required_future_contract"])

    def test_dwd_registry_topic_alone_is_not_semantic_proof(self) -> None:
        dwd = self.payload["provider_semantics"]["dwd"]
        self.assertTrue(dwd["registry_topic_tornado"])
        self.assertFalse(dwd["dedicated_tornado_capability"])
        self.assertFalse(dwd["capability_explicit_tornado_description"])
        self.assertFalse(dwd["registry_topic_alone_is_semantic_proof"])

    def test_nws_raw_fields_do_not_become_public_semantics_implicitly(self) -> None:
        nws = self.payload["provider_semantics"]["noaa_nws"]
        self.assertTrue(nws["explicit_tornado_warning_description"])
        self.assertIn("parameters", nws["retains_fields"])
        self.assertIn("not yet public", nws["rule"])

    def test_free_text_normalization_risk_is_explicit(self) -> None:
        free_text = self.payload["free_text_normalization"]
        self.assertEqual(
            free_text["current_inputs"],
            ["event", "headline", "description", "instruction"],
        )
        self.assertFalse(free_text["runtime_change_in_p3_tornado_20"])

    def test_core_invariants_remain_hard(self) -> None:
        invariants = set(self.payload["invariants"])
        for item in (
            "Tornado Warning is not a confirmed tornado.",
            "Tornado Watch is not a Tornado Warning.",
            "Radar rotation is not a confirmed tornado.",
            "Thunderstorm cell is not tornado.",
            "Waterspout remains distinct from tornado.",
            "Provider ID is not a scoring axis.",
            "Profiles remain deny-only.",
        ):
            self.assertIn(item, invariants)


if __name__ == "__main__":
    unittest.main()
