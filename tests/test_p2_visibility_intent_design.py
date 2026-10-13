"""Static contract test for the P2-VIS-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p2_visibility_intent_design.v1.json"


class P2VisibilityIntentDesignContractTest(unittest.TestCase):
    """Protect P2-VIS-30 design decisions before runtime implementation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.decisions = cls.payload["decisions"]

    def test_existing_visibility_id_becomes_three_candidate_forecast_intent(self) -> None:
        row = self.decisions["shared_visibility_forecast_intent"]
        self.assertEqual(row["public_id"], "weather.point.visibility")
        self.assertTrue(row["reuse_existing_id"])
        self.assertEqual(
            row["candidate_set"],
            [
                "open_meteo/visibility",
                "fmi/visibility",
                "smhi/visibility",
            ],
        )
        self.assertEqual(row["observation_kind"], "forecast")
        self.assertEqual(row["semantic_quantity"], "visibility_distance")
        self.assertEqual(row["canonical_unit"], "m")
        self.assertTrue(row["numeric_interchangeable"])

    def test_smhi_requires_km_to_meter_normalization(self) -> None:
        row = self.decisions["shared_visibility_forecast_intent"]
        self.assertEqual(
            row["unit_normalization"]["smhi/visibility"],
            "km_to_m",
        )

    def test_eccc_moves_to_separate_observation_path(self) -> None:
        row = self.decisions["new_specialized_visibility_observation"]
        self.assertEqual(row["public_id"], "weather.observation.visibility")
        self.assertEqual(row["candidate"], "eccc_geomet/visibility")
        self.assertEqual(row["observation_kind"], "observation")
        self.assertEqual(row["semantic_quantity"], "visibility_distance")
        self.assertEqual(row["canonical_unit"], "m")
        self.assertNotIn(
            "eccc_geomet/visibility",
            self.decisions["shared_visibility_forecast_intent"]["candidate_set"],
        )

    def test_fog_fraction_remains_specialized(self) -> None:
        row = self.decisions["specialized_fog_fraction_preserved"]
        self.assertTrue(row["preserve"])
        self.assertEqual(row["public_id"], "weather.point.fog")
        self.assertEqual(row["candidate"], "met_norway/fog")
        self.assertEqual(row["semantic_quantity"], "fog_fraction")
        self.assertEqual(row["canonical_unit"], "%")

    def test_related_products_are_not_numeric_fallbacks(self) -> None:
        paths = set(self.decisions["non_fallback_paths"])
        self.assertIn("cloud_cover_low", paths)
        self.assertIn("weather.point.weather_code", paths)
        self.assertIn("weather.point.weather_summary", paths)
        self.assertIn("weather.warning.official", paths)

    def test_provider_id_is_not_scoring_axis(self) -> None:
        self.assertFalse(self.decisions["scoring_policy"]["provider_id_axis"])
        self.assertEqual(self.decisions["scoring_policy"]["profiles"], "deny_only")
        raw = DESIGN_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("provider_priority", raw)


if __name__ == "__main__":
    unittest.main()
