"""Contract tests for the P3-THUNDER-40 runtime implementation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
HELPER_PATH = ROOT / "custom_components" / "weather_router" / "thunder_semantics.py"
CONSUMER_API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
DIAGNOSTIC_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
SMHI_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "smhi.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "weather_router_thunder_semantics_test",
        HELPER_PATH,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load thunder_semantics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P3ThunderImplementationTest(unittest.TestCase):
    """Protect the P3-THUNDER-40 runtime contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.helper = _load_helper()

    def _candidates(self, public_id: str) -> list[str]:
        values: list[str] = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    values.append(f"{provider_id}/{capability_id}")
        return values

    def test_runtime_and_contract_maps_match(self) -> None:
        self.assertEqual(self.mapping, self.contract)

    def test_thunder_candidate_sets_remain_exactly_one_and_two(self) -> None:
        self.assertEqual(
            self._candidates("weather.convection.thunderstorm_cells"),
            ["dwd/thunderstorm_cells"],
        )
        self.assertEqual(
            self._candidates("weather.point.thunder_probability"),
            [
                "met_norway/thunder_probability",
                "smhi/thunder_probability",
            ],
        )

    def test_public_capability_count_remains_226(self) -> None:
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)

    def test_cell_contract_is_hardened_without_cross_family_fallback(self) -> None:
        meta = self.mapping["public_capabilities"][
            "weather.convection.thunderstorm_cells"
        ]
        contract = meta["intent_contract"]
        self.assertEqual(meta["strategy"], "single")
        self.assertEqual(contract["resource_type"], "raster_tile")
        self.assertEqual(
            contract["measurement_method_policy"],
            "convective_cell_detection",
        )
        self.assertEqual(contract["observation_kind_policy"], "nowcast")
        self.assertEqual(contract["coverage"], "candidate_hard_bbox")
        self.assertFalse(contract["numeric_interchangeable"])

    def test_probability_contract_requires_exact_one_hour_percent(self) -> None:
        meta = self.mapping["public_capabilities"][
            "weather.point.thunder_probability"
        ]
        contract = meta["intent_contract"]
        self.assertEqual(contract["resource_type"], "value")
        self.assertEqual(contract["quantity_policy"], "thunderstorm_probability")
        self.assertEqual(contract["canonical_unit"], "%")
        self.assertEqual(contract["numeric_range_inclusive"], [0, 100])
        self.assertEqual(contract["required_interval_seconds"], 3600)
        self.assertEqual(
            contract["temporal_policy"],
            "next_1_hour_thunder_probability",
        )
        self.assertTrue(contract["numeric_interchangeable"])

    def test_met_one_hour_probability_normalizes(self) -> None:
        value = self.helper.normalize_thunder_value(
            "weather.point.thunder_probability",
            {"value": 37, "unit": "%", "period": "1h"},
        )
        self.assertEqual(value["value"], 37.0)
        self.assertEqual(value["unit"], "%")
        self.assertEqual(value["quantity"], "thunderstorm_probability")
        self.assertEqual(value["interval_seconds"], 3600)
        self.assertEqual(
            value["temporal_meaning"],
            "next_1_hour_thunder_probability",
        )

    def test_met_six_or_twelve_hour_probability_fails_closed(self) -> None:
        for period in ("6h", "12h"):
            with self.assertRaises(ValueError):
                self.helper.normalize_thunder_value(
                    "weather.point.thunder_probability",
                    {"value": 20, "unit": "%", "period": period},
                )

    def test_smhi_exact_one_hour_interval_normalizes(self) -> None:
        value = self.helper.normalize_thunder_value(
            "weather.point.thunder_probability",
            {
                "value": 25,
                "unit": "%",
                "interval_start": "2026-10-04T05:00:00Z",
                "interval_end": "2026-10-04T06:00:00Z",
            },
        )
        self.assertEqual(value["interval_seconds"], 3600)
        self.assertEqual(
            value["thunder_semantic_class"],
            "thunderstorm_probability_next_1h_point_forecast",
        )

    def test_probability_invalid_values_and_intervals_fail_closed(self) -> None:
        invalid = (
            {"value": None, "unit": "%", "period": "1h"},
            {"value": True, "unit": "%", "period": "1h"},
            {"value": -0.1, "unit": "%", "period": "1h"},
            {"value": 100.1, "unit": "%", "period": "1h"},
            {"value": 20, "unit": "1", "period": "1h"},
            {
                "value": 20,
                "unit": "%",
                "interval_start": "2026-10-04T04:00:00Z",
                "interval_end": "2026-10-04T06:00:00Z",
            },
            {"value": 20, "unit": "%"},
        )
        for entry in invalid:
            with self.subTest(entry=entry):
                with self.assertRaises(ValueError):
                    self.helper.normalize_thunder_value(
                        "weather.point.thunder_probability",
                        entry,
                    )

    def test_cell_resource_gets_explicit_thunder_semantics(self) -> None:
        value = self.helper.apply_thunder_resource_semantics(
            "weather.convection.thunderstorm_cells",
            {"type": "raster_tile"},
        )
        self.assertEqual(
            value["thunder_semantic_class"],
            "convective_thunderstorm_cell_nowcast_raster",
        )
        self.assertEqual(value["temporal_meaning"], "provider_nowcast_frames")

    def test_smhi_preserves_provider_interval_for_thunder_probability(self) -> None:
        source = SMHI_PATH.read_text(encoding="utf-8")
        self.assertIn('"intervalParametersStartTime"', source)
        self.assertIn('"interval_start"', source)
        self.assertIn('"interval_end"', source)

    def test_consumer_api_applies_thunder_normalization(self) -> None:
        source = CONSUMER_API_PATH.read_text(encoding="utf-8")
        self.assertIn("normalize_thunder_value(candidate.public_id, value)", source)
        self.assertIn(
            "apply_thunder_resource_semantics(candidate.public_id, payload)",
            source,
        )

    def test_diagnostics_export_thunder_semantics_and_interval(self) -> None:
        source = DIAGNOSTIC_PATH.read_text(encoding="utf-8")
        for marker in (
            '"thunder_semantic_class"',
            '"interval_seconds"',
            '"interval_start"',
            '"interval_end"',
            '"provider_period"',
        ):
            self.assertIn(marker, source)

    def test_probability_time_contract_allows_runtime_interval_evidence(self) -> None:
        time_contract = self.mapping["capability_time_semantics"]["providers"]
        for provider_id in ("met_norway", "smhi"):
            item = time_contract[provider_id]["thunder_probability"]
            self.assertEqual(item["interval_start"], "optional_runtime")
            self.assertEqual(item["interval_end"], "optional_runtime")

    def test_provider_priority_is_not_added(self) -> None:
        raw = MAP_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("provider_priority", raw)


if __name__ == "__main__":
    unittest.main()
