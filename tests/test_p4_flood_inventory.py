"""Static contract test for the P4-FLOOD-10 inventory."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "p4_flood_inventory.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
HAZARD_TYPES_PATH = ROOT / "custom_components" / "weather_router" / "consumer_hazard_event_types.json"
HAZARD_COMMON_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
BBK_COMMON_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "bbk_warning_common.py"
NINA_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "nina_supplementary.py"
GLOFAS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "glofas.py"
REGISTRY_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "registry.json"


class P4FloodInventoryContractTest(unittest.TestCase):
    """Keep P4-FLOOD-10 tied to the current standard-core contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.hazard_types = json.loads(HAZARD_TYPES_PATH.read_text(encoding="utf-8"))
        cls.hazard_common = HAZARD_COMMON_PATH.read_text(encoding="utf-8")
        cls.bbk_common = BBK_COMMON_PATH.read_text(encoding="utf-8")
        cls.nina = NINA_PATH.read_text(encoding="utf-8")
        cls.glofas = GLOFAS_PATH.read_text(encoding="utf-8")
        registry_raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.registry = registry_raw["providers"]

    def test_flood_family_has_ten_public_capabilities(self) -> None:
        flood = {
            key: value
            for key, value in self.mapping["public_capabilities"].items()
            if value["family"] == "flood"
        }
        self.assertEqual(len(flood), 10)
        self.assertEqual(self.inventory["summary"]["public_capabilities_family_flood"], 10)

    def test_dedicated_flood_warning_has_only_nina_candidate(self) -> None:
        actual = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if "natural_hazards.flood.warning" in public_ids:
                    actual.append(f"{provider_id}/{capability_id}")
        self.assertEqual(actual, ["nina_flood/flood_information_germany"])

    def test_flood_warning_declares_specific_subtypes(self) -> None:
        contract = self.mapping["public_capabilities"]["natural_hazards.flood.warning"]
        for hazard_type in self.inventory["hazard_types_in_scope"]:
            self.assertIn(hazard_type, contract["hazard_types"])

    def test_weather_warning_carries_heavy_rain_and_flood_subtypes(self) -> None:
        types = set(
            self.mapping["public_capabilities"]["weather.warning.official"]["hazard_types"]
        )
        self.assertIn("heavy_rain", types)
        for hazard_type in self.inventory["hazard_types_in_scope"]:
            self.assertIn(hazard_type, types)

    def test_heavy_rain_is_not_in_dedicated_flood_warning(self) -> None:
        types = self.mapping["public_capabilities"]["natural_hazards.flood.warning"][
            "hazard_types"
        ]
        self.assertNotIn("heavy_rain", types)
        self.assertEqual(self.hazard_types["hazard_types"]["heavy_rain"]["group"], "weather")

    def test_nina_inventory_records_preimplementation_reachability_gap(self) -> None:
        classifier = self.inventory["nina_flood_current_classifier"]
        self.assertEqual(
            classifier["directly_classified_types"],
            [
                "levee_failure",
                "dam_failure",
                "debris_flow",
                "surface_water_flood",
                "flash_flood",
                "flood",
            ],
        )
        self.assertEqual(
            classifier["declared_but_not_directly_classified_from_title"],
            ["glacial_lake_outburst_flood", "ice_jam_flood"],
        )

    def test_nina_classifier_now_reaches_design_added_types_from_real_titles(self) -> None:
        for marker in (
            '"glacial_lake_outburst_flood"',
            '"ice_jam_flood"',
            '"glof"',
            '"gletscherseeausbruch"',
            '"ice jam flood"',
            '"eisstau"',
        ):
            self.assertIn(marker, self.bbk_common)

    def test_general_hazard_normalizer_has_glof_and_ice_jam(self) -> None:
        self.assertIn('"glacial_lake_outburst_flood"', self.hazard_common)
        self.assertIn('"ice_jam_flood"', self.hazard_common)

    def test_nina_is_official_warning_and_opt_in(self) -> None:
        self.assertIn('source_class = "official_warning"', self.nina)
        self.assertIn('coverage = "Deutschland"', self.nina)
        entry = next(item for item in self.registry if item.get("class") == "NinaFloodProvider")
        self.assertFalse(entry["default_enabled"])

    def test_glofas_has_nine_distinct_raster_contracts(self) -> None:
        ids = [
            key
            for key, value in self.mapping["public_capabilities"].items()
            if value["family"] == "flood" and value["resource_types"] == ["raster_tile"]
        ]
        self.assertEqual(len(ids), 9)
        self.assertEqual(
            set(ids),
            set(self.inventory["glofas"]["capabilities"]),
        )

    def test_glofas_is_model_not_warning_authority(self) -> None:
        self.assertIn('"modellbasierte Frühwarninformation, keine lokale amtliche Warnung"', self.glofas)
        self.assertEqual(self.inventory["glofas"]["data_origin"], "model")
        self.assertEqual(
            self.inventory["glofas"]["measurement_method"],
            "hydrological_model",
        )
        self.assertFalse(self.inventory["glofas"]["warning_authority"])

    def test_glofas_is_opt_in(self) -> None:
        entry = next(item for item in self.registry if item.get("module") == "glofas")
        self.assertFalse(entry["default_enabled"])

    def test_related_coastal_types_remain_distinct(self) -> None:
        for item in ("storm_surge", "coastal_event"):
            self.assertEqual(
                self.hazard_types["hazard_types"][item]["group"],
                "hydrology",
            )
            self.assertIn(item, self.inventory["related_but_distinct_hazard_types"])

    def test_core_invariants_are_explicit(self) -> None:
        invariants = set(self.inventory["invariants"])
        self.assertIn("GloFAS model output is not an official warning.", invariants)
        self.assertIn("Heavy rain is not automatically a flood event.", invariants)
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)


if __name__ == "__main__":
    unittest.main()
