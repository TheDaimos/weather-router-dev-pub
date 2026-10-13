"""Static contract test for the P4-TSUNAMI-10 inventory."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "p4_tsunami_inventory.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
HAZARD_TYPES_PATH = ROOT / "custom_components" / "weather_router" / "consumer_hazard_event_types.json"
REGISTRY_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "registry.json"
JMA_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "jma.py"
NOAA_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_tsunami.py"
BOM_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "bom_tsunami.py"
BMKG_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "bmkg_tsunami.py"
GDACS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "gdacs.py"


class P4TsunamiInventoryContractTest(unittest.TestCase):
    """Keep P4-TSUNAMI-10 tied to the current standard-core contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.hazard_types = json.loads(HAZARD_TYPES_PATH.read_text(encoding="utf-8"))
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["providers"]
        cls.jma = JMA_PATH.read_text(encoding="utf-8")
        cls.noaa = NOAA_PATH.read_text(encoding="utf-8")
        cls.bom = BOM_PATH.read_text(encoding="utf-8")
        cls.bmkg = BMKG_PATH.read_text(encoding="utf-8")
        cls.gdacs = GDACS_PATH.read_text(encoding="utf-8")

    def _candidates_for(self, public_id: str) -> set[str]:
        result: set[str] = set()
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    result.add(f"{provider_id}/{capability_id}")
        return result

    def test_warning_contract_is_aggregate_hazard_feed(self) -> None:
        contract = self.mapping["public_capabilities"][
            "natural_hazards.tsunami.warnings"
        ]
        self.assertEqual(contract["family"], "tsunami")
        self.assertEqual(contract["strategy"], "aggregate")
        self.assertEqual(contract["hazard_types"], ["tsunami"])
        self.assertEqual(contract["resource_types"], ["hazard_feed"])

    def test_warning_candidates_are_official_warning_paths(self) -> None:
        self.assertEqual(
            self._candidates_for("natural_hazards.tsunami.warnings"),
            {
                "jma/official_tsunami_warnings_japan",
                "noaa_tsunami/official_tsunami_alerts",
                "bom_tsunami/official_tsunami_warnings_australia",
            },
        )

    def test_observation_and_potential_paths_are_separate(self) -> None:
        self.assertEqual(
            self._candidates_for("natural_hazards.tsunami.observations"),
            {"jma/tsunami_observations_japan"},
        )
        self.assertEqual(
            self._candidates_for("natural_hazards.tsunami.potential"),
            {"bmkg_tsunami/tsunami_potential_earthquake"},
        )
        potential = self.mapping["public_capabilities"][
            "natural_hazards.tsunami.potential"
        ]
        self.assertEqual(potential["hazard_types"], ["tsunami_potential"])

    def test_tsunami_and_potential_are_distinct_geophysical_types(self) -> None:
        types = self.hazard_types["hazard_types"]
        self.assertEqual(types["tsunami"]["group"], "geophysical")
        self.assertEqual(types["tsunami_potential"]["group"], "geophysical")
        self.assertNotEqual("tsunami", "tsunami_potential")

    def test_tsunami_core_providers_are_default_enabled(self) -> None:
        entries = {item["module"]: item for item in self.registry}
        for provider in ("jma", "noaa_tsunami", "bmkg_tsunami", "bom_tsunami"):
            self.assertTrue(entries[provider]["default_enabled"])
            self.assertIn("natural_hazards", entries[provider]["domains"])

    def test_gdacs_tsunami_stays_disaster_awareness(self) -> None:
        self.assertIn('"TS": "tsunami"', self.gdacs)
        self.assertNotIn(
            "gdacs/global_disaster_alerts_7d",
            self._candidates_for("natural_hazards.tsunami.warnings"),
        )
        path = self.inventory["public_paths"]["disaster_awareness"]
        self.assertTrue(path["aggregator"])
        self.assertFalse(path["primary_warning_authority"])

    def test_jma_keeps_warning_and_observation_source_roles_separate(self) -> None:
        self.assertIn('"source_class": "observation" if observation else "warning"', self.jma)
        self.assertIn('"certainty": "observed"', self.jma)
        self.assertIn('"alert_level": "observation"', self.jma)

    def test_bmkg_is_only_a_tsunami_potential_indicator(self) -> None:
        self.assertIn('"hazard_type": "tsunami_potential"', self.bmkg)
        self.assertIn('"source_class": "event_indicator"', self.bmkg)
        self.assertIn("tsunami_potential is not an official tsunami warning", self.bmkg)
        self.assertFalse(
            self.inventory["providers"]["bmkg_tsunami"]["official_tsunami_warning"]
        )

    def test_noaa_filters_to_active_threat_levels(self) -> None:
        for level in ('"warning"', '"advisory"', '"watch"', '"threat"'):
            self.assertIn(level, self.noaa)
        self.assertIn("active_threat", self.noaa)
        self.assertTrue(self.inventory["providers"]["noaa_tsunami"]["active_filter"])

    def test_bom_and_jma_missing_geometry_are_inventory_findings(self) -> None:
        self.assertIn('"geometry": None', self.bom)
        self.assertIn('"geometry": None', self.jma)
        findings = self.inventory["coverage_findings"]
        self.assertFalse(findings["jma_embedded_geometry"])
        self.assertFalse(findings["bom_embedded_geometry"])
        self.assertFalse(
            findings["catalog_default"]["endpoint_reachability_is_coverage"]
        )

    def test_inventory_records_current_semantic_discrepancies_without_fixing_them(self) -> None:
        ids = {
            item["id"] for item in self.inventory["current_mapping_discrepancies"]
        }
        self.assertEqual(
            ids,
            {"jma_observation_kind", "bmkg_potential_source_semantics"},
        )

    def test_core_invariants_are_explicit(self) -> None:
        invariants = set(self.inventory["invariants"])
        for expected in (
            "Tsunami potential is not an official tsunami warning.",
            "JMA tsunami observation remains observation semantics.",
            "GDACS remains disaster awareness and not a primary tsunami warning authority.",
            "Missing geometry is not outside_coverage.",
            "Endpoint reachability is not coverage proof.",
            "Provider ID is not a scoring axis.",
            "Profiles remain deny-only.",
        ):
            self.assertIn(expected, invariants)


if __name__ == "__main__":
    unittest.main()
