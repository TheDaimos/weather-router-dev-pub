"""Static contract test for the P2-CLOUD-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p2_cloud_intent_design.v1.json"


class P2CloudIntentDesignContractTest(unittest.TestCase):
    """Keep P2-CLOUD-30 design decisions stable until implementation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.decisions = cls.payload["decisions"]

    def test_four_existing_shared_point_ids_are_reused(self) -> None:
        rows = self.decisions["shared_point_intents"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            {row["public_id"] for row in rows},
            {
                "weather.point.cloud_cover",
                "weather.point.cloud_cover_low",
                "weather.point.cloud_cover_mid",
                "weather.point.cloud_cover_high",
            },
        )
        self.assertTrue(all(row["reuse_existing_id"] for row in rows))
        self.assertTrue(all(row["canonical_unit"] == "%" for row in rows))
        self.assertTrue(all(row["observation_kind"] == "forecast" for row in rows))

    def test_eccc_is_separate_observation_path(self) -> None:
        row = self.decisions["new_specialized_public_capability"]
        self.assertEqual(row["public_id"], "weather.observation.cloud_cover")
        self.assertEqual(row["candidate"], "eccc_geomet/cloud_cover")
        self.assertEqual(row["observation_kind"], "observation")
        self.assertIsNone(row["canonical_unit"])

        total = next(
            row
            for row in self.decisions["shared_point_intents"]
            if row["public_id"] == "weather.point.cloud_cover"
        )
        self.assertNotIn("eccc_geomet/cloud_cover", total["candidate_set"])

    def test_satellite_cloud_layer_requires_machine_coverage(self) -> None:
        row = self.decisions["shared_visual_cloud_layer"]
        self.assertEqual(row["public_id"], "weather.satellite.clouds")
        self.assertEqual(row["coverage_policy"], "required")
        self.assertEqual(
            row["candidate_set"],
            ["dwd/satellite_clouds", "eumetview/satellite_clouds"],
        )

    def test_nasa_specialized_products_are_preserved_without_cross_product_fallback(self) -> None:
        preserved = self.decisions["specialized_satellite_products_preserved"]
        self.assertEqual(len(preserved), 12)
        self.assertTrue(self.decisions["no_cross_product_satellite_fallback"]["enabled"])
        self.assertFalse(
            self.decisions["no_new_shared_nasa_product_class_intents"]["create"]
        )

    def test_provider_id_is_not_scoring_axis(self) -> None:
        self.assertFalse(self.decisions["scoring_policy"]["provider_id_axis"])
        raw = DESIGN_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("provider_priority", raw)


if __name__ == "__main__":
    unittest.main()
