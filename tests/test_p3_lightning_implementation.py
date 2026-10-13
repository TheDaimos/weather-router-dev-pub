"""Contract tests for the P3-LIGHTNING-40 runtime implementation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
HELPER_PATH = ROOT / "custom_components" / "weather_router" / "lightning_semantics.py"
CONSUMER_API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
DIAGNOSTIC_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("weather_router_lightning_semantics_test", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load lightning_semantics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P3LightningImplementationTest(unittest.TestCase):
    """Protect the P3-LIGHTNING-40 runtime contracts."""

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

    def test_all_eight_lightning_candidate_sets_remain_single_and_exact(self) -> None:
        expected = {
            "weather.lightning.density": ["dwd/lightning_density"],
            "weather.lightning.observed.density": ["eccc_lightning/lightning_density_2_5km"],
            "weather.lightning.observed.events": ["fmi_lightning/lightning_strikes_observed"],
            "weather.lightning.observed.nearest_distance": ["fmi_lightning/lightning_nearest_distance"],
            "weather.lightning.observed.nearest_azimuth": ["fmi_lightning/lightning_nearest_azimuth"],
            "weather.lightning.satellite.glm_east.lcfa": ["noaa_goes_glm/glm_east_lcfa"],
            "weather.lightning.satellite.glm_west.lcfa": ["noaa_goes_glm/glm_west_lcfa"],
            "weather.lightning.satellite.mtg_li.accumulated_flashes": ["eumetsat_mtg_li/mtg_li_accumulated_flashes"],
        }
        self.assertEqual({key: self._candidates(key) for key in expected}, expected)

    def test_all_lightning_public_contracts_are_hardened(self) -> None:
        ids = [key for key in self.mapping["public_capabilities"] if key.startswith("weather.lightning.")]
        self.assertEqual(len(ids), 8)
        for public_id in ids:
            meta = self.mapping["public_capabilities"][public_id]
            self.assertEqual(meta["strategy"], "single")
            self.assertIn("intent_contract", meta)
            self.assertEqual(meta["intent_contract"]["observation_kind_policy"], "observation")

    def test_density_paths_remain_separate(self) -> None:
        dwd = self.mapping["public_capabilities"]["weather.lightning.density"]["intent_contract"]
        eccc = self.mapping["public_capabilities"]["weather.lightning.observed.density"]["intent_contract"]
        self.assertEqual(dwd["quantity_policy"], "lightning_density")
        self.assertEqual(eccc["quantity_policy"], "lightning_density")
        self.assertIsNone(dwd["canonical_unit"])
        self.assertEqual(eccc["canonical_unit"], "km^-2 min^-1")
        self.assertEqual(dwd["coverage"], "candidate_hard_bbox")
        self.assertEqual(eccc["coverage"], "candidate_specific_unknown_allowed")

    def test_nearest_values_normalize_units_and_ranges(self) -> None:
        normalize = self.helper.normalize_lightning_value
        distance = normalize(
            "weather.lightning.observed.nearest_distance",
            {"value": 12.5, "unit": "km"},
        )
        self.assertEqual(distance["value"], 12.5)
        self.assertEqual(distance["unit"], "km")
        self.assertEqual(distance["quantity"], "distance")
        self.assertTrue(distance["event_present"])

        azimuth = normalize(
            "weather.lightning.observed.nearest_azimuth",
            {"value": 359.9, "unit": "°"},
        )
        self.assertEqual(azimuth["unit"], "°")
        self.assertEqual(azimuth["quantity"], "azimuth")
        self.assertTrue(azimuth["event_present"])

        empty = normalize(
            "weather.lightning.observed.nearest_distance",
            {"value": None, "unit": "km"},
        )
        self.assertIsNone(empty["value"])
        self.assertFalse(empty["event_present"])

        for public_id, entry in (
            ("weather.lightning.observed.nearest_distance", {"value": -1, "unit": "km"}),
            ("weather.lightning.observed.nearest_distance", {"value": 1, "unit": "m"}),
            ("weather.lightning.observed.nearest_azimuth", {"value": 360, "unit": "°"}),
            ("weather.lightning.observed.nearest_azimuth", {"value": True, "unit": "°"}),
        ):
            with self.assertRaises(ValueError):
                normalize(public_id, entry)

    def test_event_and_satellite_ground_strike_guards_are_explicit(self) -> None:
        apply = self.helper.apply_lightning_resource_semantics
        events = apply(
            "weather.lightning.observed.events",
            {"events": [], "event_count": 0, "window_seconds": 1200},
        )
        self.assertFalse(events["ground_strike_only"])
        self.assertEqual(events["lightning_semantic_class"], "terrestrial_network_lightning_event")

        for public_id in (
            "weather.lightning.satellite.glm_east.lcfa",
            "weather.lightning.satellite.glm_west.lcfa",
            "weather.lightning.satellite.mtg_li.accumulated_flashes",
        ):
            value = apply(public_id, {})
            self.assertFalse(value["ground_strike_confirmation"])

    def test_event_window_is_fail_closed(self) -> None:
        apply = self.helper.apply_lightning_resource_semantics
        with self.assertRaises(ValueError):
            apply("weather.lightning.observed.events", {"window_seconds": 600})

    def test_consumer_api_applies_lightning_semantics_and_preserves_event_fields(self) -> None:
        source = CONSUMER_API_PATH.read_text(encoding="utf-8")
        self.assertIn("normalize_lightning_value(candidate.public_id, value)", source)
        self.assertIn("apply_lightning_resource_semantics(candidate.public_id, payload)", source)
        for field in ("peak_current_ka", "multiplicity", "cloud_indicator", "lightning_type", "ellipse_major_km"):
            self.assertIn(f'"{field}"', source)

    def test_diagnostics_export_lightning_semantic_fields(self) -> None:
        source = DIAGNOSTIC_PATH.read_text(encoding="utf-8")
        for field in (
            "lightning_semantic_class",
            "ground_strike_only",
            "ground_strike_confirmation",
            "event_present",
            "density_unit",
            "aggregation_seconds",
        ):
            self.assertIn(f'payload.get("{field}")' if field != "event_present" else 'item.get("event_present")', source)

    def test_runtime_diagnostics_separate_core_from_local_extensions(self) -> None:
        source = CONSUMER_API_PATH.read_text(encoding="utf-8")
        self.assertIn('"weather_router_extension_id"', source)
        self.assertIn('candidate_scope = "extension" if extension_id else "standard_core"', source)
        self.assertIn("candidate_scope=candidate_scope", source)
        self.assertIn("extension_id=extension_id", source)

    def test_public_capability_count_remains_226(self) -> None:
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)

    def test_provider_priority_and_cross_provider_fallback_are_not_added(self) -> None:
        raw = MAP_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("provider_priority", raw)
        for public_id in (
            "weather.lightning.density",
            "weather.lightning.observed.density",
            "weather.lightning.satellite.glm_east.lcfa",
            "weather.lightning.satellite.glm_west.lcfa",
        ):
            self.assertEqual(len(self._candidates(public_id)), 1)


if __name__ == "__main__":
    unittest.main()
