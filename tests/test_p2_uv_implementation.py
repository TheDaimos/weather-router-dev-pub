"""Contract tests for the P2-UV-40 runtime implementation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
HELPER_PATH = ROOT / "custom_components" / "weather_router" / "uv_semantics.py"
CONSUMER_API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
DIAGNOSTIC_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
OPEN_METEO_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "open_meteo.py"
MET_NORWAY_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "met_norway.py"


def _load_uv_helper():
    spec = importlib.util.spec_from_file_location("weather_router_uv_semantics_test", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load uv_semantics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P2UvImplementationTest(unittest.TestCase):
    """Protect the P2-UV-40 runtime contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.uv = _load_uv_helper()

    def _candidates(self, public_id: str) -> list[str]:
        values: list[str] = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    values.append(f"{provider_id}/{capability_id}")
        return values

    def test_runtime_and_contract_maps_match(self) -> None:
        self.assertEqual(self.mapping, self.contract)

    def test_uv_candidate_sets_are_exactly_1_2_1_1(self) -> None:
        self.assertEqual(self._candidates("weather.point.uv_index"), ["open_meteo/uv_index"])
        self.assertEqual(
            self._candidates("weather.point.uv_index_clear_sky"),
            ["open_meteo/uv_index_clear_sky", "met_norway/uv_index"],
        )
        self.assertEqual(
            self._candidates("weather.point.uv_index_max_today"),
            ["open_meteo/uv_index_max_today"],
        )
        self.assertEqual(
            self._candidates("weather.point.uv_index_clear_sky_max_today"),
            ["open_meteo/uv_index_clear_sky_max_today"],
        )

    def test_all_uv_intents_use_dimensionless_unit_one(self) -> None:
        for public_id in (
            "weather.point.uv_index",
            "weather.point.uv_index_clear_sky",
            "weather.point.uv_index_max_today",
            "weather.point.uv_index_clear_sky_max_today",
        ):
            contract = self.mapping["public_capabilities"][public_id]["intent_contract"]
            self.assertEqual(contract["quantity_policy"], "uv_index")
            self.assertEqual(contract["unit_policy"], "dimensionless_one")
            self.assertEqual(contract["canonical_unit"], "1")
            self.assertEqual(contract["observation_kind_policy"], "forecast")

    def test_sky_and_temporal_policies_stay_separate(self) -> None:
        meta = self.mapping["public_capabilities"]
        self.assertEqual(
            meta["weather.point.uv_index"]["intent_contract"]["sky_condition_policy"],
            "all_sky_or_cloud_affected",
        )
        self.assertEqual(
            meta["weather.point.uv_index_clear_sky"]["intent_contract"]["sky_condition_policy"],
            "clear_sky",
        )
        self.assertEqual(
            meta["weather.point.uv_index"]["intent_contract"]["temporal_policy"],
            "current_or_near_current_forecast",
        )
        self.assertEqual(
            meta["weather.point.uv_index_max_today"]["intent_contract"]["temporal_policy"],
            "maximum_for_local_day_today",
        )

    def test_uv_normalization_is_fail_closed_and_adds_semantics(self) -> None:
        normalize = self.uv.normalize_uv_index_value
        current = normalize("weather.point.uv_index", {"value": 4.2, "unit": None})
        self.assertEqual(current["value"], 4.2)
        self.assertEqual(current["unit"], "1")
        self.assertEqual(current["sky_condition"], "all_sky_or_cloud_affected")
        self.assertEqual(current["temporal_meaning"], "current_or_near_current_forecast")

        clear = normalize("weather.point.uv_index_clear_sky", {"value": 5, "unit": "1"})
        self.assertEqual(clear["unit"], "1")
        self.assertEqual(clear["sky_condition"], "clear_sky")

        daily = normalize(
            "weather.point.uv_index_clear_sky_max_today",
            {"value": 6.3, "unit": "", "local_day": "2026-10-03"},
        )
        self.assertEqual(daily["temporal_meaning"], "maximum_for_local_day_today")
        self.assertEqual(daily["local_day"], "2026-10-03")

        for entry in (
            {"value": None, "unit": "1"},
            {"value": True, "unit": "1"},
            {"value": "5", "unit": "1"},
            {"value": -0.1, "unit": "1"},
            {"value": 5.0, "unit": "W/m²"},
        ):
            with self.assertRaises(ValueError):
                normalize("weather.point.uv_index", entry)

    def test_unrelated_values_are_unchanged(self) -> None:
        entry = {"value": 10.0, "unit": "°C"}
        self.assertEqual(
            self.uv.normalize_uv_index_value("weather.point.temperature", entry),
            entry,
        )

    def test_consumer_api_applies_uv_normalizer(self) -> None:
        source = CONSUMER_API_PATH.read_text(encoding="utf-8")
        self.assertIn("from .uv_semantics import normalize_uv_index_value", source)
        self.assertIn("value = normalize_uv_index_value(candidate.public_id, value)", source)

    def test_provider_uv_units_are_explicitly_dimensionless(self) -> None:
        open_meteo = OPEN_METEO_PATH.read_text(encoding="utf-8")
        met_norway = MET_NORWAY_PATH.read_text(encoding="utf-8")
        for capability in (
            "uv_index",
            "uv_index_clear_sky",
            "uv_index_max_today",
            "uv_index_clear_sky_max_today",
        ):
            self.assertIn(f'CapabilityInfo("{capability}",', open_meteo)
        self.assertIn('CapabilityInfo("uv_index", "UV-Index", "1", "model")', open_meteo)
        self.assertIn('CapabilityInfo("uv_index_clear_sky", "UV-Index · klarer Himmel", "1", "model")', open_meteo)
        self.assertIn('CapabilityInfo("uv_index", "UV-Index klarer Himmel", "1", "model", "value"', met_norway)

    def test_open_meteo_uv_unit_fallback_has_capability_map(self) -> None:
        open_meteo = OPEN_METEO_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "_CAPABILITY_MAP = {item.id: item for item in _CAPABILITIES}",
            open_meteo,
        )
        self.assertEqual(open_meteo.count("_CAPABILITY_MAP[capability_id].unit"), 2)

    def test_daily_open_meteo_values_preserve_local_day(self) -> None:
        source = OPEN_METEO_PATH.read_text(encoding="utf-8")
        self.assertIn('"time_source": "daily_today"', source)
        self.assertIn('"local_day": local_day', source)

    def test_diagnostics_export_uv_semantic_fields(self) -> None:
        source = DIAGNOSTIC_PATH.read_text(encoding="utf-8")
        for field in ("sky_condition", "temporal_meaning", "time_source", "local_day"):
            self.assertIn(f'item.get("{field}")', source)

    def test_no_suvi_or_cloud_candidate_is_mapped_into_uv_index(self) -> None:
        all_candidates = set()
        for public_id in (
            "weather.point.uv_index",
            "weather.point.uv_index_clear_sky",
            "weather.point.uv_index_max_today",
            "weather.point.uv_index_clear_sky_max_today",
        ):
            all_candidates.update(self._candidates(public_id))
        self.assertTrue(all("suvi" not in item for item in all_candidates))
        self.assertTrue(all("cloud" not in item for item in all_candidates))

    def test_runtime_public_capability_count_is_226(self) -> None:
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)

    def test_provider_priority_is_not_added(self) -> None:
        raw = MAP_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("provider_priority", raw)


if __name__ == "__main__":
    unittest.main()
