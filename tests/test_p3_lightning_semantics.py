"""Static contract test for the P3-LIGHTNING-20 semantic classification."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p3_lightning_semantics.v1.json"


class P3LightningSemanticsContractTest(unittest.TestCase):
    """Keep P3-LIGHTNING-20 boundaries stable until intent design changes them explicitly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
        cls.candidates = cls.payload["candidate_classification"]

    def test_inventory_count_is_preserved(self) -> None:
        self.assertEqual(len(self.candidates), 8)
        self.assertEqual(
            len({(item["provider"], item["capability"]) for item in self.candidates}),
            8,
        )

    def test_density_candidates_share_broad_class_but_not_interchangeability(self) -> None:
        items = [
            item for item in self.candidates
            if item["semantic_class"] == "observed_lightning_density_grid"
        ]
        self.assertEqual(
            {(item["provider"], item["capability"]) for item in items},
            {
                ("dwd", "lightning_density"),
                ("eccc_lightning", "lightning_density_2_5km"),
            },
        )
        self.assertTrue(
            all(
                item["compatibility"]
                == "same_broad_density_class_not_interchangeable_yet"
                for item in items
            )
        )
        self.assertIsNone(
            self.payload["semantic_families"]["observed_lightning_density_grid"][
                "canonical_unit_for_future_routing"
            ]
        )

    def test_fmi_event_feed_is_not_ground_strike_only(self) -> None:
        item = next(
            item for item in self.candidates
            if item["provider"] == "fmi_lightning"
            and item["capability"] == "lightning_strikes_observed"
        )
        self.assertEqual(item["resource_type"], "event_feed")
        self.assertFalse(item["ground_strike_only"])

    def test_nearest_geometry_values_remain_distinct(self) -> None:
        distance = next(
            item for item in self.candidates
            if item["capability"] == "lightning_nearest_distance"
        )
        azimuth = next(
            item for item in self.candidates
            if item["capability"] == "lightning_nearest_azimuth"
        )
        self.assertEqual(distance["quantity"], "distance")
        self.assertEqual(distance["canonical_unit_for_future_routing"], "km")
        self.assertEqual(azimuth["quantity"], "azimuth")
        self.assertEqual(azimuth["canonical_unit_for_future_routing"], "degree")

    def test_noaa_glm_candidates_share_file_class_only(self) -> None:
        items = [
            item for item in self.candidates
            if item["semantic_class"] == "satellite_total_lightning_l2_lcfa_file"
        ]
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["resource_type"] == "data_file" for item in items))
        self.assertTrue(all(item["coverage"] == "unknown" for item in items))
        self.assertTrue(
            all(
                item["compatibility"]
                == "same_glm_product_class_coverage_unresolved"
                for item in items
            )
        )

    def test_mtg_li_raster_stays_separate_from_glm_files(self) -> None:
        item = next(
            item for item in self.candidates
            if item["provider"] == "eumetsat_mtg_li"
        )
        self.assertEqual(
            item["semantic_class"],
            "satellite_total_lightning_accumulation_raster",
        )
        self.assertEqual(item["resource_type"], "raster_tile")
        self.assertEqual(item["compatibility"], "separate_satellite_raster_product")

    def test_satellite_products_never_claim_ground_strike_confirmation(self) -> None:
        satellite = [
            item for item in self.candidates
            if item["semantic_class"].startswith("satellite_total_lightning_")
        ]
        self.assertEqual(len(satellite), 3)
        self.assertTrue(
            all(item["ground_strike_confirmation"] is False for item in satellite)
        )

    def test_semantic_rules_preserve_hard_boundaries(self) -> None:
        rules = self.payload["rules"]
        self.assertTrue(rules["density_is_not_event"])
        self.assertTrue(rules["event_feed_is_not_derived_nearest_value"])
        self.assertTrue(rules["distance_is_not_azimuth"])
        self.assertTrue(rules["raster_is_not_data_file"])
        self.assertTrue(rules["satellite_total_lightning_is_not_confirmed_ground_strike"])
        self.assertTrue(rules["observation_is_not_warning_or_probability"])
        self.assertTrue(rules["unknown_coverage_stays_unknown"])
        self.assertTrue(rules["private_extensions_outside_standard_core_contract"])

    def test_no_provider_priority_or_scoring_decision_is_encoded(self) -> None:
        raw = SEMANTICS_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("provider_priority", raw)
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("routing_score", raw)


if __name__ == "__main__":
    unittest.main()
