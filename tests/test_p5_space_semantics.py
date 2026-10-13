"""Static contract test for the P5-SPACE-20 semantics."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = ROOT / "docs" / "p5_space_semantics.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
SWPC_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_swpc.py"


class P5SpaceSemanticsContractTest(unittest.TestCase):
    """Lock semantic separation before P5-SPACE-30 intent design."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.semantics = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.swpc = SWPC_PATH.read_text(encoding="utf-8")

    def test_existing_space_classes_remain_distinct(self) -> None:
        classes = self.semantics["existing_classes"]
        self.assertEqual(classes["solar_euv_observation"]["observation_kind"], "observation")
        self.assertEqual(classes["orbital_live_imagery"]["resource_type"], "live_stream")
        self.assertEqual(classes["lunar_reference_imagery"]["observation_kind"], "reference")
        self.assertEqual(classes["astronomical_ephemeris"]["observation_kind"], "estimate")

    def test_suvi_semantics_are_observation_not_forecast(self) -> None:
        source = self.mapping["capability_source_semantics"]["providers"]["noaa_swpc"]
        observation = self.mapping["capability_observation_semantics"]["providers"]["noaa_swpc"]
        suvi = [item for item in source if item.startswith("solar_suvi_")]
        self.assertEqual(len(suvi), 6)
        for capability in suvi:
            self.assertEqual(source[capability]["data_origin"], "space_sensor")
            self.assertEqual(source[capability]["measurement_method"], "solar_euv_imaging")
            self.assertEqual(observation[capability]["observation_kind"], "observation")

    def test_coordinate_spaces_remain_non_interchangeable(self) -> None:
        coverage = self.mapping["capability_coverage_semantics"]["providers"]
        suvi = {
            key: value for key, value in coverage["noaa_swpc"].items()
            if key.startswith("solar_suvi_")
        }
        self.assertEqual(len(suvi), 6)
        for item in suvi.values():
            self.assertEqual(item["coordinate_space"], "sun")
        self.assertEqual(
            coverage["nasa_moon"]["moon_lro_wac_global"]["coordinate_space"],
            "moon",
        )
        self.assertEqual(
            coverage["nasa_iss"]["iss_earth_live"]["coordinate_space"],
            "orbital",
        )

    def test_semantic_snapshot_records_astronomy_coverage_gap(self) -> None:
        decisions = self.semantics["coverage_decisions"]
        self.assertEqual(decisions["astronomy_current"], "unknown/unknown/none/earth")
        self.assertIn("worldwide Earth point", decisions["astronomy_target_semantics"])

    def test_semantic_snapshot_records_aurora_as_unrouted_at_phase_20(self) -> None:
        self.assertTrue(self.semantics["aurora_semantics"]["ovation_planned"])
        self.assertFalse(
            self.semantics["aurora_semantics"]["current_public_contract_present"]
        )

    def test_hard_semantic_boundaries_are_recorded(self) -> None:
        invariants = set(self.semantics["invariants"])
        for expected in (
            "SUVI observation is not aurora probability.",
            "Aurora oval is not point visibility.",
            "Kp is not local aurora visibility.",
            "Astronomically visible is not cloud free.",
            "Worldwide point coverage is not a coordinate-free Global request.",
            "Endpoint reachability is not coverage proof.",
            "Provider ID is not a scoring axis.",
            "Profiles remain deny-only.",
        ):
            self.assertIn(expected, invariants)


if __name__ == "__main__":
    unittest.main()
