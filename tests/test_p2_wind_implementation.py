"""P2-WIND-40 implementation contract tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
WIND_HELPER_PATH = ROOT / "custom_components" / "weather_router" / "wind_semantics.py"
CONSUMER_API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"


def _load_wind_helper():
    spec = importlib.util.spec_from_file_location("weather_router_wind_semantics_test", WIND_HELPER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load wind_semantics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P2WindImplementationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.wind = _load_wind_helper()

    def _candidates(self, public_id: str) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    result.append((provider_id, capability_id))
        return result

    def test_shared_wind_candidate_sets(self) -> None:
        self.assertEqual(len(self._candidates("weather.point.wind_speed")), 5)
        self.assertEqual(len(self._candidates("weather.point.wind_gusts")), 4)
        direction = self._candidates("weather.point.wind_direction")
        self.assertEqual(len(direction), 5)
        self.assertNotIn(("eccc_geomet", "wind_direction"), direction)

    def test_eccc_station_direction_is_specialized(self) -> None:
        self.assertEqual(
            self.mapping["providers"]["eccc_geomet"]["wind_direction"],
            ["weather.observation.wind_direction_at_max_speed"],
        )
        specialized = self.mapping["public_capabilities"][
            "weather.observation.wind_direction_at_max_speed"
        ]
        self.assertFalse(specialized["intent_contract"]["numeric_interchangeable"])
        self.assertEqual(
            self.mapping["capability_physical_semantics"]["providers"]["eccc_geomet"][
                "wind_direction"
            ]["quantity"],
            "wind_direction_at_max_speed",
        )

    def test_gust_quantity_is_distinct_from_generic_speed(self) -> None:
        physical = self.mapping["capability_physical_semantics"]["providers"]
        for provider_id in ("open_meteo", "met_norway", "fmi", "smhi"):
            self.assertEqual(
                physical[provider_id]["wind_gusts"]["quantity"],
                "wind_gust_speed",
            )
        self.assertEqual(
            physical["met_norway"]["nowcast_wind_gusts"]["quantity"],
            "wind_gust_speed",
        )

    def test_generic_direction_quantity_is_from_direction(self) -> None:
        physical = self.mapping["capability_physical_semantics"]["providers"]
        for provider_id in ("open_meteo", "met_norway", "noaa_nws", "fmi", "smhi"):
            self.assertEqual(
                physical[provider_id]["wind_direction"]["quantity"],
                "wind_from_direction",
            )
        self.assertEqual(
            physical["met_norway"]["nowcast_wind_direction"]["quantity"],
            "wind_from_direction",
        )

    def test_shared_contracts_are_numeric_point_forecasts(self) -> None:
        public = self.mapping["public_capabilities"]
        for public_id, quantity, unit in (
            ("weather.point.wind_speed", "wind_speed", "m/s"),
            ("weather.point.wind_gusts", "wind_gust_speed", "m/s"),
            ("weather.point.wind_direction", "wind_from_direction", "°"),
        ):
            contract = public[public_id]["intent_contract"]
            self.assertEqual(contract["resource_type"], "value")
            self.assertTrue(contract["numeric_interchangeable"])
            self.assertEqual(contract["quantity_policy"], quantity)
            self.assertEqual(contract["canonical_unit"], unit)
            self.assertEqual(contract["observation_kind_policy"], "forecast")

    def test_shared_wind_unit_normalization(self) -> None:
        normalize = self.wind.normalize_shared_wind_value
        converted = normalize(
            "weather.point.wind_speed",
            {"value": 36.0, "unit": "km/h"},
        )
        self.assertAlmostEqual(converted["value"], 10.0)
        self.assertEqual(converted["unit"], "m/s")

        unchanged = normalize(
            "weather.point.wind_gusts",
            {"value": 12.5, "unit": "m/s"},
        )
        self.assertEqual(unchanged["value"], 12.5)
        self.assertEqual(unchanged["unit"], "m/s")

        specialized = normalize(
            "weather.nowcast.wind_speed",
            {"value": 36.0, "unit": "km/h"},
        )
        self.assertEqual(specialized["value"], 36.0)
        self.assertEqual(specialized["unit"], "km/h")

    def test_direction_is_validated_and_normalized(self) -> None:
        normalized = self.wind.normalize_shared_wind_value(
            "weather.point.wind_direction",
            {"value": 270, "unit": "degrees"},
        )
        self.assertEqual(normalized["value"], 270.0)
        self.assertEqual(normalized["unit"], "°")

    def test_invalid_or_missing_shared_values_fail_closed(self) -> None:
        for entry in (
            {"value": 10.0, "unit": "knots"},
            {"value": None, "unit": "m/s"},
            {"value": "10", "unit": "m/s"},
        ):
            with self.assertRaises(ValueError):
                self.wind.normalize_shared_wind_value(
                    "weather.point.wind_speed",
                    entry,
                )
        with self.assertRaises(ValueError):
            self.wind.normalize_shared_wind_value(
                "weather.point.wind_direction",
                {"value": 90.0, "unit": "radian"},
            )

    def test_consumer_api_applies_shared_wind_normalizer(self) -> None:
        source = CONSUMER_API_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "from .wind_semantics import normalize_shared_wind_value",
            source,
        )
        self.assertIn(
            "value = normalize_shared_wind_value(candidate.public_id, entry)",
            source,
        )


if __name__ == "__main__":
    unittest.main()
