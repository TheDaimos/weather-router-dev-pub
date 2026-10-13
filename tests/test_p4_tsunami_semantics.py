"""Static contract test for P4-TSUNAMI-20 semantics."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p4_tsunami_semantics.v1.json"


class P4TsunamiSemanticsContractTest(unittest.TestCase):
    """Protect tsunami warning, observation, potential and coverage boundaries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))

    def test_tsunami_potential_is_neither_warning_nor_observation(self) -> None:
        potential = self.payload["canonical_hazard_types"]["tsunami_potential"]
        self.assertFalse(potential["official_warning"])
        self.assertFalse(potential["observed_tsunami"])

    def test_tsunami_hazard_type_alone_does_not_prove_observation(self) -> None:
        tsunami = self.payload["canonical_hazard_types"]["tsunami"]
        self.assertFalse(tsunami["implies_observed_wave"])
        self.assertFalse(tsunami["implies_active_warning"])

    def test_alert_stage_is_separate_from_wave_semantics(self) -> None:
        stage = self.payload["alert_stage"]
        self.assertTrue(stage["separate_from_wave_observation"])
        self.assertTrue(stage["separate_from_wave_height"])
        self.assertTrue(stage["severity_is_not_wave_height"])
        self.assertIn("warning", stage["active_threat_stages"])
        self.assertIn("canceled", stage["non_active_or_informational_stages"])

    def test_cancellation_and_no_threat_do_not_make_global_claims(self) -> None:
        termination = self.payload["termination_semantics"]
        self.assertFalse(termination["canceled"]["active_threat"])
        self.assertFalse(termination["canceled"]["proves_no_tsunami_occurred"])
        self.assertFalse(termination["no_threat"]["active_threat"])
        self.assertFalse(termination["no_threat"]["global_no_tsunami_claim"])

    def test_expected_and_observed_wave_values_are_distinct(self) -> None:
        wave = self.payload["wave_semantics"]
        self.assertFalse(wave["expected"]["observation"])
        self.assertTrue(wave["observed"]["observation"])
        self.assertNotEqual(
            set(wave["expected"]["fields"]),
            set(wave["observed"]["fields"]),
        )

    def test_jma_observation_target_is_not_warning_event(self) -> None:
        correction = self.payload["capability_mapping_corrections"][
            "jma_tsunami_observations_japan"
        ]
        self.assertEqual(correction["current"]["observation_kind"], "warning_event")
        self.assertEqual(correction["target"]["observation_kind"], "observation")
        self.assertEqual(correction["target"]["source_class"], "observation")

    def test_bmkg_potential_target_uses_seismic_observation_semantics(self) -> None:
        correction = self.payload["capability_mapping_corrections"][
            "bmkg_tsunami_potential_earthquake"
        ]
        target = correction["target"]
        self.assertEqual(target["data_origin"], "seismic_network")
        self.assertEqual(target["measurement_method"], "seismic_event_catalog")
        self.assertEqual(target["observation_kind"], "observation")
        self.assertEqual(target["source_class"], "event_indicator")
        self.assertEqual(target["hazard_type"], "tsunami_potential")

    def test_source_roles_are_not_interchangeable(self) -> None:
        roles = self.payload["source_roles"]
        self.assertFalse(
            roles["official_tsunami_warning_authority"]["interchangeable_with_observation"]
        )
        self.assertFalse(
            roles["official_tsunami_warning_authority"]["interchangeable_with_potential"]
        )
        self.assertFalse(
            roles["tsunami_potential_indicator"]["official_warning"]
        )
        self.assertFalse(
            roles["disaster_awareness_aggregator"]["primary_warning_authority"]
        )

    def test_domestic_and_international_roles_remain_distinct(self) -> None:
        provider = self.payload["provider_semantics"]
        self.assertTrue(provider["jma"]["nwptac_international_role_separate"])
        self.assertTrue(provider["bom_jatwc"]["iotwms_tsp_role_separate"])
        self.assertFalse(provider["noaa"]["global_warning_authority"])

    def test_coverage_never_uses_endpoint_or_provider_identity_as_proof(self) -> None:
        coverage = self.payload["coverage"]
        self.assertFalse(coverage["endpoint_reachability_is_coverage"])
        self.assertFalse(coverage["missing_geometry_is_outside_coverage"])
        self.assertFalse(coverage["provider_identity_is_coverage"])
        self.assertFalse(coverage["region_text_alone_is_point_coverage"])
        self.assertFalse(coverage["current_global_primary_warning_coverage"])

    def test_core_invariants_are_explicit(self) -> None:
        invariants = set(self.payload["invariants"])
        for expected in (
            "Tsunami potential is not an official tsunami warning.",
            "JMA tsunami observation is not a warning event.",
            "Expected wave height is not observed wave height.",
            "GDACS is not a primary tsunami warning authority.",
            "Missing geometry is not outside_coverage.",
            "Endpoint reachability is not coverage proof.",
            "Provider ID is not a scoring axis.",
            "Profiles remain deny-only.",
        ):
            self.assertIn(expected, invariants)


if __name__ == "__main__":
    unittest.main()
