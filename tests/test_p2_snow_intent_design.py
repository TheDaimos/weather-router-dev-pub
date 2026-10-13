"""Static contract test for the P2-SNOW-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p2_snow_intent_design.v1.json"


class P2SnowIntentDesignContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.decisions = cls.payload["decisions"]

    def test_existing_snowfall_id_is_reused_without_fake_shared_intent(self) -> None:
        row = self.decisions["snowfall_point_contract"]
        self.assertEqual(row["public_id"], "weather.point.snowfall")
        self.assertTrue(row["reuse_existing_id"])
        self.assertFalse(row["create_new_shared_id"])
        self.assertEqual(row["candidate_set"], ["open_meteo/snowfall"])

    def test_snowfall_contract_is_cm_interval_accumulation(self) -> None:
        row = self.decisions["snowfall_point_contract"]
        self.assertEqual(row["semantic_quantity"], "snowfall_amount")
        self.assertEqual(row["canonical_unit"], "cm")
        self.assertEqual(row["observation_kind"], "forecast")
        self.assertEqual(row["accumulation_policy"], "preceding_runtime_interval_sum")
        self.assertEqual(row["runtime_interval_source"], "provider current.interval")

    def test_related_condition_and_warning_paths_do_not_join_snowfall(self) -> None:
        self.assertFalse(
            self.decisions["related_condition_paths_preserved"][
                "participate_in_snowfall_amount_routing"
            ]
        )
        self.assertFalse(
            self.decisions["warning_path_preserved"][
                "participate_in_snowfall_amount_routing"
            ]
        )
        self.assertFalse(
            self.decisions["precipitation_peers_preserved"][
                "participate_in_snowfall_amount_routing"
            ]
        )

    def test_snow_leopard_correction_only_removes_weather_topic(self) -> None:
        row = self.decisions["snow_leopard_topic_correction"]
        self.assertEqual(row["remove_topic"], "snow_ice")
        self.assertEqual(row["preserve_topics"], ["biological_hazards"])
        self.assertEqual(
            row["preserve_public_capability"],
            "biological_hazards.occurrence.snow_leopard.density",
        )

    def test_provider_id_is_not_scoring_axis(self) -> None:
        self.assertFalse(self.decisions["scoring_policy"]["provider_id_axis"])
        raw = DESIGN_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("provider_priority", raw)


if __name__ == "__main__":
    unittest.main()
