"""Static contract test for the P3-LIGHTNING-30 intent design."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "p3_lightning_intent_design.v1.json"


class P3LightningIntentDesignTest(unittest.TestCase):
    """Keep Lightning intent boundaries stable until runtime implementation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cls.intents = cls.payload["intents"]

    def test_no_new_public_ids_and_all_eight_are_preserved(self) -> None:
        decisions = self.payload["decisions"]
        self.assertEqual(decisions["new_public_capabilities"], [])
        self.assertEqual(len(self.intents), 8)
        self.assertEqual(
            set(self.intents),
            set(decisions["preserved_public_capabilities"]),
        )

    def test_all_current_lightning_intents_remain_single_candidate(self) -> None:
        self.assertEqual(
            self.payload["decisions"]["multi_candidate_public_capabilities"],
            [],
        )
        self.assertTrue(
            all(len(spec["candidates"]) == 1 for spec in self.intents.values())
        )

    def test_density_paths_remain_separate(self) -> None:
        dwd = self.intents["weather.lightning.density"]
        eccc = self.intents["weather.lightning.observed.density"]
        self.assertEqual(dwd["candidates"], ["dwd/lightning_density"])
        self.assertEqual(
            eccc["candidates"],
            ["eccc_lightning/lightning_density_2_5km"],
        )
        self.assertEqual(dwd["quantity_policy"], "lightning_density")
        self.assertEqual(eccc["quantity_policy"], "lightning_density")
        self.assertIsNone(dwd["canonical_unit"])
        self.assertEqual(eccc["canonical_unit"], "km^-2 min^-1")

    def test_fmi_event_contract_is_not_ground_strike_only(self) -> None:
        events = self.intents["weather.lightning.observed.events"]
        self.assertEqual(events["resource_type"], "event_feed")
        self.assertFalse(events["ground_strike_only"])
        self.assertEqual(
            events["temporal_policy"],
            "events_within_20_minute_query_window",
        )

    def test_nearest_distance_and_azimuth_are_distinct(self) -> None:
        distance = self.intents["weather.lightning.observed.nearest_distance"]
        azimuth = self.intents["weather.lightning.observed.nearest_azimuth"]
        self.assertEqual(distance["quantity_policy"], "distance")
        self.assertEqual(distance["canonical_unit"], "km")
        self.assertEqual(azimuth["quantity_policy"], "azimuth")
        self.assertEqual(azimuth["canonical_unit"], "°")
        self.assertEqual(
            distance["temporal_policy"],
            "nearest_event_within_20_minute_window",
        )
        self.assertEqual(distance["temporal_policy"], azimuth["temporal_policy"])

    def test_noaa_glm_east_west_remain_separate_until_machine_coverage(self) -> None:
        east = self.intents["weather.lightning.satellite.glm_east.lcfa"]
        west = self.intents["weather.lightning.satellite.glm_west.lcfa"]
        self.assertEqual(east["resource_type"], "data_file")
        self.assertEqual(west["resource_type"], "data_file")
        self.assertFalse(east["ground_strike_confirmation"])
        self.assertFalse(west["ground_strike_confirmation"])
        self.assertEqual(east["coverage"], "candidate_specific_unknown_allowed")
        self.assertEqual(west["coverage"], "candidate_specific_unknown_allowed")
        self.assertNotEqual(east["candidates"], west["candidates"])

    def test_mtg_li_raster_is_not_merged_with_glm_files(self) -> None:
        mtg = self.intents[
            "weather.lightning.satellite.mtg_li.accumulated_flashes"
        ]
        east = self.intents["weather.lightning.satellite.glm_east.lcfa"]
        self.assertEqual(mtg["resource_type"], "raster_tile")
        self.assertEqual(east["resource_type"], "data_file")
        self.assertFalse(mtg["ground_strike_confirmation"])

    def test_forbidden_fallbacks_protect_deferred_merge_boundaries(self) -> None:
        forbidden = set(self.payload["forbidden_fallbacks"])
        for item in {
            "dwd_density_to_eccc_density_until_unit_time_coverage_harmonized",
            "eccc_density_to_dwd_density_until_unit_time_coverage_harmonized",
            "glm_east_to_glm_west_until_machine_coverage",
            "glm_west_to_glm_east_until_machine_coverage",
            "mtg_li_raster_to_goes_lcfa_file",
            "observed_lightning_to_warnings",
        }:
            self.assertIn(item, forbidden)

    def test_invariants_keep_routing_provider_neutral(self) -> None:
        invariants = self.payload["invariants"]
        self.assertTrue(invariants["provider_id_is_not_scoring_axis"])
        self.assertTrue(invariants["profiles_remain_deny_only"])
        self.assertTrue(invariants["unknown_coverage_stays_unknown"])
        self.assertTrue(invariants["endpoint_reachability_is_not_coverage"])
        self.assertTrue(invariants["no_provider_specific_consumer_logic"])
        self.assertTrue(invariants["private_extensions_outside_standard_core_contract"])

    def test_no_provider_priority_or_score_is_encoded(self) -> None:
        raw = DESIGN_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("provider_priority", raw)
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("routing_score", raw)


if __name__ == "__main__":
    unittest.main()
