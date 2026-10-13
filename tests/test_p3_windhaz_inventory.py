"""Static contract test for the P3-WINDHAZ-10 inventory."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "p3_windhaz_inventory.v1.json"
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
DRAFT_MAP_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
HAZARD_TYPES_PATH = ROOT / "custom_components" / "weather_router" / "consumer_hazard_event_types.json"
REGISTRY_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "registry.json"
HAZARD_COMMON_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"


class P3WindHazInventoryContractTest(unittest.TestCase):
    """Keep the P3-WINDHAZ-10 inventory tied to the real standard core."""

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

    def test_no_dedicated_windhaz_public_capability_exists(self) -> None:
        for mapping in (self.mapping, self.draft_mapping):
            ids = mapping["public_capabilities"]
            self.assertFalse(any("downburst" in item.casefold() for item in ids))
            self.assertFalse(any("windhaz" in item.casefold() for item in ids))
        self.assertEqual(
            self.inventory["summary"]["dedicated_public_capabilities"],
            0,
        )

    def test_warning_path_carries_windstorm_and_downburst(self) -> None:
        public = self.mapping["public_capabilities"]["weather.warning.official"]
        self.assertEqual(public["strategy"], "aggregate")
        self.assertIn("hazard_feed", public["resource_types"])
        self.assertIn("windstorm", public["hazard_types"])
        self.assertIn("downburst", public["hazard_types"])

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

    def test_stable_wind_hazard_types_exist(self) -> None:
        hazards = self.hazard_types["hazard_types"]
        self.assertEqual(hazards["windstorm"]["group"], "weather")
        self.assertEqual(hazards["downburst"]["group"], "convective_hazards")

    def test_primary_normalization_order_is_inventory_fact(self) -> None:
        downburst = self.hazard_common.index('"downburst"')
        severe = self.hazard_common.index('"severe_thunderstorm"')
        windstorm = self.hazard_common.index('"windstorm"')
        self.assertLess(downburst, severe)
        self.assertLess(severe, windstorm)
        self.assertEqual(
            self.inventory["primary_normalization"]["relevant_order"],
            ["downburst", "severe_thunderstorm", "windstorm"],
        )

    def test_downburst_keywords_are_explicit_and_narrow(self) -> None:
        for keyword in ("downburst", "microburst", "macroburst", "fallböe", "fallboe"):
            self.assertIn(keyword, self.hazard_common)
        keywords = set(self.inventory["hazard_types"]["downburst"]["keywords"])
        self.assertNotIn("damaging wind", keywords)
        self.assertNotIn("wind gust", keywords)

    def test_dwd_and_nws_have_severe_wind_registry_topic(self) -> None:
        selected = {
            item["module"]: item
            for item in self.registry
            if item.get("module") in {"dwd", "noaa_nws"}
        }
        self.assertEqual(set(selected), {"dwd", "noaa_nws"})
        for item in selected.values():
            self.assertIn("severe_wind", item.get("topics", []))

    def test_separate_numeric_wind_contracts_remain_distinct(self) -> None:
        expected = {
            "weather.point.wind_speed",
            "weather.point.wind_gusts",
            "weather.point.wind_direction",
            "weather.point.wind_summary",
            "weather.nowcast.wind_speed",
            "weather.nowcast.wind_gusts",
            "weather.nowcast.wind_direction",
            "weather.model.wind_10m.layer",
        }
        self.assertEqual(
            set(self.inventory["separate_wind_data_contracts"]),
            expected,
        )
        for public_id in expected:
            self.assertIn(public_id, self.mapping["public_capabilities"])

    def test_forecast_gust_contract_is_not_warning_contract(self) -> None:
        gust = self.mapping["public_capabilities"]["weather.point.wind_gusts"]
        self.assertEqual(gust["resource_types"], ["value"])
        self.assertEqual(gust["intent_contract"]["observation_kind_policy"], "forecast")
        self.assertEqual(gust["intent_contract"]["quantity_policy"], "wind_gust_speed")
        self.assertEqual(gust["intent_contract"]["canonical_unit"], "m/s")

    def test_core_routing_invariants_remain_explicit(self) -> None:
        invariants = set(self.inventory["invariants"])
        self.assertIn("Provider ID is not a scoring axis.", invariants)
        self.assertIn("Profiles remain deny-only.", invariants)
        self.assertIn(
            "P3-WINDHAZ-10 does not change runtime normalization ordering.",
            invariants,
        )
        self.assertIn(
            "P2-WIND numeric contracts remain semantically unchanged.",
            invariants,
        )


if __name__ == "__main__":
    unittest.main()
