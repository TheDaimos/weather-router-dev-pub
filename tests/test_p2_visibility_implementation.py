"""Contract tests for the P2-VIS-40 runtime implementation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
HELPER_PATH = ROOT / "custom_components" / "weather_router" / "visibility_semantics.py"
CONSUMER_API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"


def _load_visibility_helper():
    spec = importlib.util.spec_from_file_location(
        "weather_router_visibility_semantics_test",
        HELPER_PATH,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load visibility_semantics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P2VisibilityImplementationTest(unittest.TestCase):
    """Protect the P2-VIS-40 runtime contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.visibility = _load_visibility_helper()

    def _candidates(self, public_id: str) -> list[str]:
        values: list[str] = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    values.append(f"{provider_id}/{capability_id}")
        return values

    def test_shared_visibility_forecast_has_exactly_three_candidates(self) -> None:
        self.assertEqual(
            self._candidates("weather.point.visibility"),
            [
                "open_meteo/visibility",
                "fmi/visibility",
                "smhi/visibility",
            ],
        )
        self.assertNotIn(
            "eccc_geomet/visibility",
            self._candidates("weather.point.visibility"),
        )

    def test_eccc_visibility_is_separate_observation(self) -> None:
        self.assertEqual(
            self._candidates("weather.observation.visibility"),
            ["eccc_geomet/visibility"],
        )
        meta = self.mapping["public_capabilities"]["weather.observation.visibility"]
        contract = meta["intent_contract"]
        self.assertEqual(contract["observation_kind_policy"], "observation")
        self.assertEqual(contract["quantity_policy"], "visibility_distance")
        self.assertEqual(contract["canonical_unit"], "m")
        self.assertFalse(contract["numeric_interchangeable"])

    def test_shared_visibility_contract_is_meter_forecast(self) -> None:
        meta = self.mapping["public_capabilities"]["weather.point.visibility"]
        contract = meta["intent_contract"]
        self.assertEqual(contract["kind"], "numeric_point")
        self.assertTrue(contract["numeric_interchangeable"])
        self.assertEqual(contract["observation_kind_policy"], "forecast")
        self.assertEqual(contract["quantity_policy"], "visibility_distance")
        self.assertEqual(contract["canonical_unit"], "m")
        self.assertEqual(contract["unit_policy"], "normalize_to_meters")

    def test_fog_fraction_remains_single_candidate_percent_forecast(self) -> None:
        self.assertEqual(
            self._candidates("weather.point.fog"),
            ["met_norway/fog"],
        )
        contract = self.mapping["public_capabilities"]["weather.point.fog"][
            "intent_contract"
        ]
        self.assertEqual(contract["quantity_policy"], "fog_fraction")
        self.assertEqual(contract["canonical_unit"], "%")
        self.assertEqual(contract["observation_kind_policy"], "forecast")
        self.assertFalse(contract["numeric_interchangeable"])

    def test_visibility_unit_normalization(self) -> None:
        normalize = self.visibility.normalize_visibility_value

        meters = normalize(
            "weather.point.visibility",
            {"value": 1250.0, "unit": "m"},
        )
        self.assertEqual(meters["value"], 1250.0)
        self.assertEqual(meters["unit"], "m")

        kilometers = normalize(
            "weather.point.visibility",
            {"value": 12.5, "unit": "km"},
        )
        self.assertEqual(kilometers["value"], 12500.0)
        self.assertEqual(kilometers["unit"], "m")

        observation = normalize(
            "weather.observation.visibility",
            {"value": 8000, "unit": "m"},
        )
        self.assertEqual(observation["value"], 8000.0)
        self.assertEqual(observation["unit"], "m")

    def test_fog_fraction_unit_is_validated(self) -> None:
        normalized = self.visibility.normalize_visibility_value(
            "weather.point.fog",
            {"value": 72, "unit": "%"},
        )
        self.assertEqual(normalized["value"], 72.0)
        self.assertEqual(normalized["unit"], "%")

    def test_invalid_visibility_values_fail_closed(self) -> None:
        normalize = self.visibility.normalize_visibility_value
        for entry in (
            {"value": 10.0, "unit": "mi"},
            {"value": None, "unit": "m"},
            {"value": "1000", "unit": "m"},
        ):
            with self.assertRaises(ValueError):
                normalize("weather.point.visibility", entry)

        with self.assertRaises(ValueError):
            normalize("weather.point.fog", {"value": 50, "unit": "fraction"})

    def test_unrelated_point_values_are_unchanged(self) -> None:
        entry = {"value": 7.5, "unit": "°C"}
        self.assertEqual(
            self.visibility.normalize_visibility_value(
                "weather.point.temperature",
                entry,
            ),
            entry,
        )

    def test_consumer_api_applies_visibility_normalizer(self) -> None:
        source = CONSUMER_API_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "from .visibility_semantics import normalize_visibility_value",
            source,
        )
        self.assertIn(
            "value = normalize_visibility_value(candidate.public_id, value)",
            source,
        )

    def test_runtime_public_capability_count_is_226(self) -> None:
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)

    def test_provider_priority_is_not_added(self) -> None:
        raw = MAP_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("provider_priority", raw)


if __name__ == "__main__":
    unittest.main()
