"""Static contract test for the P3-WINDHAZ-20 semantic classification."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p3_windhaz_semantics.v1.json"


class P3WindHazSemanticsContractTest(unittest.TestCase):
    """Protect the semantic separation of severe wind and downburst."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))

    def test_broad_and_specific_official_alert_classes_are_distinct(self) -> None:
        classes = self.payload["semantic_classes"]
        self.assertIn("official_wind_alert_event", classes)
        self.assertIn("official_downburst_alert_event", classes)
        self.assertEqual(
            classes["official_wind_alert_event"]["transport"],
            "weather.warning.official",
        )
        self.assertEqual(
            classes["official_downburst_alert_event"]["transport"],
            "weather.warning.official",
        )

    def test_downburst_requires_specific_terms(self) -> None:
        keywords = set(self.payload["downburst_specific_keywords"])
        self.assertEqual(
            keywords,
            {"downburst", "microburst", "macroburst", "fallböe", "fallboe"},
        )
        self.assertNotIn("damaging wind", keywords)
        self.assertNotIn("wind gusts", keywords)

    def test_broad_wind_evidence_is_not_generic_word_wind(self) -> None:
        self.assertIn(
            "Do not use isolated generic word wind",
            self.payload["broad_wind_evidence_rule"],
        )
        examples = set(self.payload["broad_wind_evidence_examples"])
        self.assertIn("damaging winds", examples)
        self.assertIn("wind gusts", examples)
        self.assertIn("orkan", examples)

    def test_primary_hazard_is_not_complete_semantics(self) -> None:
        primary = self.payload["primary_hazard_semantics"]
        self.assertEqual(
            primary["relevant_order"],
            ["downburst", "severe_thunderstorm", "windstorm"],
        )
        self.assertFalse(primary["primary_label_is_complete_semantics"])
        self.assertFalse(primary["runtime_change_in_p3_windhaz_20"])

    def test_specific_downburst_semantics_take_precedence(self) -> None:
        precedence = self.payload["semantic_precedence"]
        self.assertTrue(precedence["downburst_over_broad_wind"])

    def test_explicit_and_contextual_evidence_are_distinct(self) -> None:
        scope = self.payload["windhaz_evidence_scope"]
        self.assertEqual(scope["explicit_event"]["fields"], ["event", "headline"])
        self.assertEqual(
            scope["contextual_text"]["fields"],
            ["description", "instruction"],
        )
        self.assertTrue(scope["explicit_precedence"])

    def test_severe_thunderstorm_is_not_automatically_wind_hazard(self) -> None:
        overlap = self.payload["severe_thunderstorm_overlap"]
        self.assertFalse(overlap["severe_thunderstorm_is_automatically_windhaz"])
        self.assertTrue(
            overlap["explicit_wind_evidence_can_add_official_wind_alert_event"]
        )

    def test_numeric_wind_contracts_remain_separate(self) -> None:
        numeric = self.payload["numeric_wind_contracts"]
        self.assertTrue(numeric["remain_separate"])
        self.assertFalse(numeric["high_numeric_value_is_official_warning"])
        self.assertFalse(numeric["high_gust_is_downburst"])
        self.assertEqual(len(numeric["public_ids"]), 8)

    def test_observation_and_radar_classes_are_not_implemented(self) -> None:
        classes = self.payload["observation_classes"]
        self.assertEqual(
            classes["observed_or_reported_wind_damage_event"],
            "not_implemented",
        )
        self.assertEqual(
            classes["confirmed_downburst_observation_event"],
            "not_implemented",
        )
        self.assertEqual(
            classes["downburst_radar_or_nowcast_signature"],
            "not_implemented",
        )

    def test_core_invariants_remain_explicit(self) -> None:
        invariants = set(self.payload["invariants"])
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)
        self.assertIn("P2-WIND contracts remain semantically unchanged.", invariants)
        self.assertIn("High gust speed is not downburst.", invariants)


if __name__ == "__main__":
    unittest.main()
