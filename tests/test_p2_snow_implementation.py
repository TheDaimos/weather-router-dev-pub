"""P2-SNOW-40 implementation contract tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
MIRROR_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
SNOW_HELPER_PATH = ROOT / "custom_components" / "weather_router" / "snow_semantics.py"
CONSUMER_API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
DIAGNOSTIC_CORE_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
TIME_CONTRACT_PATH = ROOT / "custom_components" / "weather_router" / "consumer_time_contract.py"


def _load_time_contract_helper():
    spec = importlib.util.spec_from_file_location(
        "weather_router_consumer_time_contract_test",
        TIME_CONTRACT_PATH,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load consumer_time_contract.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_snow_helper():
    spec = importlib.util.spec_from_file_location(
        "weather_router_snow_semantics_test",
        SNOW_HELPER_PATH,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load snow_semantics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P2SnowImplementationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.mirror = json.loads(MIRROR_PATH.read_text(encoding="utf-8"))
        cls.snow = _load_snow_helper()
        cls.time_contract = _load_time_contract_helper()

    def _candidates(self, public_id: str) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    result.append((provider_id, capability_id))
        return result

    def test_runtime_map_equals_contract_mirror(self) -> None:
        self.assertEqual(self.mapping, self.mirror)

    def test_runtime_public_capability_count_is_226(self) -> None:
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)

    def test_snowfall_has_exactly_one_direct_candidate(self) -> None:
        self.assertEqual(
            self._candidates("weather.point.snowfall"),
            [("open_meteo", "snowfall")],
        )

    def test_snowfall_public_contract_is_cm_interval_forecast(self) -> None:
        row = self.mapping["public_capabilities"]["weather.point.snowfall"]
        contract = row["intent_contract"]
        self.assertEqual(contract["resource_type"], "value")
        self.assertFalse(contract["numeric_interchangeable"])
        self.assertEqual(contract["quantity_policy"], "snowfall_amount")
        self.assertEqual(contract["canonical_unit"], "cm")
        self.assertEqual(contract["observation_kind_policy"], "forecast")
        self.assertEqual(
            contract["accumulation_policy"],
            "provider_runtime_interval",
        )
        self.assertTrue(contract["runtime_interval_required"])

    def test_runtime_time_contract_validator_accepts_shipped_snowfall_contract(self) -> None:
        self.time_contract.validate_time_semantics_contract(
            self.mapping,
            self.mapping["providers"],
        )

    def test_runtime_time_contract_validator_rejects_unknown_accumulation_state(self) -> None:
        mutated = json.loads(json.dumps(self.mapping))
        mutated["capability_time_semantics"]["providers"]["open_meteo"]["snowfall"][
            "accumulation_period"
        ] = "unknown_runtime_interval"
        with self.assertRaises(ValueError):
            self.time_contract.validate_time_semantics_contract(
                mutated,
                mutated["providers"],
            )

    def test_candidate_time_semantics_preserve_runtime_interval(self) -> None:
        row = self.mapping["capability_time_semantics"]["providers"][
            "open_meteo"
        ]["snowfall"]
        self.assertEqual(
            row["accumulation_period"],
            "provider_runtime_interval",
        )
        self.assertEqual(row["interval_end"], "optional_runtime")
        self.assertEqual(row["interval_start"], "optional_runtime")

    def test_snow_leopard_is_not_in_meteorological_snow_topic(self) -> None:
        row = self.mapping["capability_topic_assignments"]["providers"][
            "gbif_biodiversity"
        ]["occurrence_density_snow_leopard"]
        self.assertEqual(row["topics"], ["biological_hazards"])
        self.assertNotIn("snow_ice", row["topics"])

    def test_related_paths_are_not_added_to_snowfall(self) -> None:
        candidates = set(self._candidates("weather.point.snowfall"))
        self.assertNotIn(("open_meteo", "weather_code"), candidates)
        self.assertNotIn(("smhi", "weather_code"), candidates)
        self.assertNotIn(("jma", "weather_code"), candidates)
        self.assertNotIn(("noaa_nws", "weather_summary"), candidates)
        self.assertNotIn(("dwd", "official_weather_warnings"), candidates)

    def test_snowfall_runtime_normalization(self) -> None:
        normalized = self.snow.normalize_snowfall_value(
            "weather.point.snowfall",
            {"value": 0.7, "unit": "cm", "field": "snowfall"},
            {"interval": 900},
        )
        self.assertEqual(normalized["value"], 0.7)
        self.assertEqual(normalized["unit"], "cm")
        self.assertEqual(
            normalized["accumulation_period"],
            "preceding_runtime_interval",
        )
        self.assertEqual(normalized["interval_seconds"], 900)

    def test_snowfall_runtime_normalization_fails_closed(self) -> None:
        for entry, result in (
            ({"value": 1.0, "unit": "mm"}, {"interval": 900}),
            ({"value": None, "unit": "cm"}, {"interval": 900}),
            ({"value": 1.0, "unit": "cm"}, {"interval": None}),
            ({"value": 1.0, "unit": "cm"}, {"interval": 0}),
        ):
            with self.assertRaises(ValueError):
                self.snow.normalize_snowfall_value(
                    "weather.point.snowfall",
                    entry,
                    result,
                )

    def test_diagnostics_expose_runtime_accumulation_interval(self) -> None:
        source = DIAGNOSTIC_CORE_PATH.read_text(encoding="utf-8")
        self.assertIn('"accumulation_period": (', source)
        self.assertIn('item.get("accumulation_period")', source)
        self.assertIn('"interval_seconds": (', source)
        self.assertIn('item.get("interval_seconds")', source)

    def test_consumer_api_applies_snowfall_normalizer(self) -> None:
        source = CONSUMER_API_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "from .snow_semantics import normalize_snowfall_value",
            source,
        )
        self.assertIn(
            "value = normalize_snowfall_value(",
            source,
        )

    def test_provider_priority_is_not_added(self) -> None:
        raw = MAP_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("provider_priority", raw)


if __name__ == "__main__":
    unittest.main()
