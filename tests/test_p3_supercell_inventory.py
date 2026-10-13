"""Static contract test for the P3-SUPERCELL-10 inventory."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "p3_supercell_inventory.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
DRAFT_MAP_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
HAZARD_TYPES_PATH = ROOT / "custom_components" / "weather_router" / "consumer_hazard_event_types.json"
REGISTRY_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "registry.json"
HAZARD_COMMON_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
DWD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "dwd.py"
NWS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_nws.py"


class P3SupercellInventoryContractTest(unittest.TestCase):
    """Keep the P3-SUPERCELL-10 inventory tied to the real standard core."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.draft_mapping = json.loads(DRAFT_MAP_PATH.read_text(encoding="utf-8"))
        cls.hazard_types = json.loads(HAZARD_TYPES_PATH.read_text(encoding="utf-8"))
        registry_raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.registry = (
            registry_raw if isinstance(registry_raw, list) else registry_raw["providers"]
        )
        cls.hazard_common = HAZARD_COMMON_PATH.read_text(encoding="utf-8")
        cls.dwd = DWD_PATH.read_text(encoding="utf-8")
        cls.nws = NWS_PATH.read_text(encoding="utf-8")

    def test_no_dedicated_supercell_public_capability_exists(self) -> None:
        for mapping in (self.mapping, self.draft_mapping):
            public_ids = mapping["public_capabilities"]
            dedicated = [
                item
                for item in public_ids
                if "supercell" in item.casefold() or "superzelle" in item.casefold()
            ]
            self.assertEqual(dedicated, [])
        self.assertEqual(self.inventory["summary"]["dedicated_public_capabilities"], 0)

    def test_warning_path_carries_supercell(self) -> None:
        public = self.mapping["public_capabilities"]["weather.warning.official"]
        self.assertEqual(public["strategy"], "aggregate")
        self.assertIn("hazard_feed", public["resource_types"])
        self.assertIn("supercell", public["hazard_types"])

    def test_warning_candidate_set_is_exactly_dwd_and_nws(self) -> None:
        actual = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if "weather.warning.official" in public_ids:
                    actual.append(f"{provider_id}/{capability_id}")
        self.assertEqual(
            actual,
            [
                "dwd/official_weather_warnings",
                "noaa_nws/official_weather_alerts",
            ],
        )

    def test_stable_supercell_hazard_type_exists(self) -> None:
        supercell = self.hazard_types["hazard_types"]["supercell"]
        self.assertEqual(supercell["group"], "convective_hazards")
        self.assertEqual(supercell["name"], "Superzelle")

    def test_inventory_records_pre_implementation_supercell_keywords(self) -> None:
        self.assertEqual(
            self.inventory["hazard_type"]["current_keywords"],
            ["supercell", "superzelle", "mesocyclone", "mesozyklone"],
        )
        # P3-SUPERCELL-10 records the checkpoint that existed during inventory.
        # Later phases may legitimately harden runtime matching without rewriting history.
        self.assertIn('"supercell"', self.hazard_common)
        self.assertIn('"superzelle"', self.hazard_common)

    def test_primary_normalization_order_is_inventory_fact(self) -> None:
        waterspout = self.hazard_common.index('"waterspout"')
        tornado = self.hazard_common.index('"tornado"')
        supercell = self.hazard_common.index('"supercell"')
        downburst = self.hazard_common.index('"downburst"')
        severe = self.hazard_common.index('"severe_thunderstorm"')
        hail = self.hazard_common.index('("hail", ("hail", "hagel"))')
        self.assertLess(waterspout, tornado)
        self.assertLess(tornado, supercell)
        self.assertLess(supercell, downburst)
        self.assertLess(downburst, severe)
        self.assertLess(severe, hail)
        self.assertEqual(
            self.inventory["primary_normalization"]["relevant_order"],
            [
                "waterspout",
                "tornado",
                "supercell",
                "downburst",
                "severe_thunderstorm",
                "hail",
            ],
        )

    def test_no_registry_supercell_topic_exists(self) -> None:
        selected = {
            item["module"]: item
            for item in self.registry
            if item.get("module") in {"dwd", "noaa_nws"}
        }
        self.assertEqual(set(selected), {"dwd", "noaa_nws"})
        for item in selected.values():
            self.assertNotIn("supercell", item.get("topics", []))
        self.assertTrue(
            all(
                provider["registry_topic_supercell"] is False
                for provider in self.inventory["warning_providers"]
            )
        )

    def test_warning_capability_descriptions_do_not_name_supercell(self) -> None:
        for source, capability_id in (
            (self.dwd, 'id="official_weather_warnings"'),
            (self.nws, 'id="official_weather_alerts"'),
        ):
            start = source.index(capability_id)
            end = source.index("documentation_url=", start)
            capability_block = source[start : end + 300].casefold()
            self.assertNotIn("supercell", capability_block)
            self.assertNotIn("superzelle", capability_block)
        self.assertTrue(
            all(
                provider["capability_explicit_supercell_text"] is False
                for provider in self.inventory["warning_providers"]
            )
        )

    def test_thunderstorm_cells_explicitly_do_not_guarantee_supercell_semantics(self) -> None:
        contract = self.mapping["public_capabilities"]["weather.convection.thunderstorm_cells"]
        self.assertEqual(contract["resource_types"], ["raster_tile"])
        self.assertIn(
            "tornado_hail_downburst_supercell_semantics",
            contract["intent_contract"]["non_guarantees"],
        )
        inventory = self.inventory["related_but_non_equivalent_contracts"][
            "weather.convection.thunderstorm_cells"
        ]
        self.assertEqual(
            inventory["explicit_non_guarantee"],
            "tornado_hail_downburst_supercell_semantics",
        )

    def test_thunder_probability_is_not_supercell_probability(self) -> None:
        contract = self.mapping["public_capabilities"]["weather.point.thunder_probability"]
        self.assertEqual(contract["resource_types"], ["value"])
        self.assertEqual(
            contract["intent_contract"]["quantity_policy"],
            "thunderstorm_probability",
        )
        self.assertEqual(
            self.inventory["summary"]["dedicated_supercell_probability_public_capabilities"],
            0,
        )

    def test_no_dedicated_rotation_or_mesocyclone_public_id_exists(self) -> None:
        public_ids = set(self.mapping["public_capabilities"])
        self.assertFalse(any("mesocycl" in item.casefold() for item in public_ids))
        self.assertFalse(any("rotation" in item.casefold() for item in public_ids))
        self.assertEqual(
            self.inventory["summary"]["dedicated_radar_rotation_signature_public_capabilities"],
            0,
        )
        self.assertEqual(
            self.inventory["summary"]["dedicated_mesocyclone_public_capabilities"],
            0,
        )

    def test_inventory_does_not_prejudge_mesocyclone_semantics(self) -> None:
        invariants = set(self.inventory["invariants"])
        self.assertIn(
            "P3-SUPERCELL-10 makes no decision that mesocyclone is sufficient supercell evidence.",
            invariants,
        )
        self.assertIn(
            "P3-SUPERCELL-10 does not change runtime normalization ordering.",
            invariants,
        )
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)


if __name__ == "__main__":
    unittest.main()
