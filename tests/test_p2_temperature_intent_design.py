"""Static contract test for the P2-TEMP-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p2_temperature_intent_design.v1.json"


class P2TemperatureIntentDesignContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.decisions = cls.payload["decisions"]

    def test_existing_temperature_point_id_is_reused_for_six_forecasts(self) -> None:
        row = self.decisions["shared_point_intent"]
        self.assertEqual(row["public_id"], "weather.point.temperature")
        self.assertTrue(row["reuse_existing_id"])
        self.assertEqual(len(row["candidate_set"]), 6)
        self.assertEqual(row["observation_kind"], "forecast")
        self.assertEqual(row["semantic_quantity"], "air_temperature")
        self.assertEqual(row["canonical_unit"], "°C")

    def test_eccc_moves_to_separate_observation_path(self) -> None:
        row = self.decisions["new_specialized_public_capability"]
        self.assertEqual(row["public_id"], "weather.observation.temperature")
        self.assertEqual(row["candidate"], "eccc_geomet/temperature")
        self.assertEqual(row["observation_kind"], "observation")
        self.assertNotIn(
            "eccc_geomet/temperature",
            self.decisions["shared_point_intent"]["candidate_set"],
        )

    def test_specialized_paths_are_preserved(self) -> None:
        self.assertTrue(self.decisions["specialized_nowcast_preserved"]["preserve"])
        self.assertTrue(self.decisions["specialized_model_layer_preserved"]["preserve"])
        self.assertEqual(
            len(self.decisions["specialized_fire_temperature_preserved"]), 2
        )
        self.assertFalse(self.decisions["fire_temperature_numeric_routing"])

    def test_provider_id_is_not_scoring_axis(self) -> None:
        self.assertFalse(self.decisions["scoring_policy"]["provider_id_axis"])
        raw = DESIGN_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("provider_priority", raw)


if __name__ == "__main__":
    unittest.main()
