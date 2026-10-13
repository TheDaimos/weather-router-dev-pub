"""Static contract test for P4-TROPICAL-20 semantics."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p4_tropical_semantics.v1.json"


class P4TropicalSemanticsContractTest(unittest.TestCase):
    """Protect tropical-system lifecycle, intensity and source-role boundaries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))

    def test_potential_is_not_confirmed_tropical_cyclone(self) -> None:
        lifecycle = self.payload["lifecycle_semantics"]
        self.assertFalse(
            lifecycle["potential_tropical_cyclone"]["confirmed_tropical_cyclone"]
        )

    def test_post_tropical_is_not_current_tropical_cyclone(self) -> None:
        lifecycle = self.payload["lifecycle_semantics"]
        self.assertFalse(
            lifecycle["post_tropical_cyclone"]["confirmed_tropical_cyclone"]
        )

    def test_confirmed_stages_remain_distinct(self) -> None:
        lifecycle = self.payload["lifecycle_semantics"]
        for key in (
            "tropical_depression",
            "tropical_storm",
            "hurricane_strength_tropical_cyclone",
        ):
            self.assertTrue(lifecycle[key]["confirmed_tropical_cyclone"])

    def test_regional_names_do_not_split_physical_family(self) -> None:
        regional = self.payload["regional_terminology"]
        self.assertFalse(regional["physical_family_split"])
        self.assertIn("hurricane", regional["examples"])
        self.assertIn("typhoon", regional["examples"])

    def test_intensity_does_not_create_global_class_without_measurement_semantics(self) -> None:
        intensity = self.payload["intensity_semantics"]
        self.assertTrue(intensity["source_reported_classification_first"])
        self.assertFalse(
            intensity["derive_global_class_from_wind_without_measurement_semantics"]
        )

    def test_alert_stage_is_separate_from_classification_and_intensity(self) -> None:
        stage = self.payload["alert_stage"]
        self.assertTrue(stage["separate_from_system_classification"])
        self.assertTrue(stage["separate_from_intensity"])
        self.assertTrue(stage["potential_tropical_cyclone_can_have_alerts"])

    def test_forecast_products_are_not_observed_impact_geometry(self) -> None:
        products = self.payload["forecast_products"]
        self.assertFalse(products["track"]["observed_damage_path"])
        self.assertFalse(products["cone"]["hazard_area"])
        self.assertFalse(products["cone"]["observed_impact_area"])
        self.assertFalse(products["wind_speed_probability"]["observed_wind"])

    def test_storm_surge_remains_distinct(self) -> None:
        surge = self.payload["storm_surge"]
        self.assertEqual(surge["distinct_hazard_type"], "storm_surge")
        self.assertFalse(surge["tropical_cyclone_implies_storm_surge"])
        self.assertFalse(surge["surge_resource_link_implies_separate_event"])

    def test_source_roles_are_not_interchangeable(self) -> None:
        roles = self.payload["source_roles"]
        self.assertFalse(
            roles["primary_tropical_cyclone_authority"]["interchangeable_with_other_roles"]
        )
        self.assertFalse(
            roles["general_official_weather_warning"]["interchangeable_with_primary_system_feed"]
        )
        self.assertFalse(
            roles["disaster_awareness_aggregator"]["primary_warning_authority"]
        )
        self.assertFalse(
            roles["official_aviation_warning"]["general_public_warning"]
        )

    def test_nhc_is_not_global_coverage(self) -> None:
        coverage = self.payload["coverage"]
        self.assertFalse(coverage["nhc_is_global"])
        self.assertTrue(coverage["unknown_remains_unknown"])
        self.assertFalse(coverage["endpoint_reachability_is_coverage"])

    def test_core_invariants_are_explicit(self) -> None:
        invariants = set(self.payload["invariants"])
        self.assertIn(
            "Potential Tropical Cyclone is not a confirmed tropical cyclone.",
            invariants,
        )
        self.assertIn(
            "Post-Tropical Cyclone is not a current tropical cyclone.",
            invariants,
        )
        self.assertIn(
            "Tropical cyclone is not automatically storm surge.",
            invariants,
        )
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)


if __name__ == "__main__":
    unittest.main()
