"""Contract tests for the P2-TEMP-40 runtime implementation."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"


class P2TemperatureImplementationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))

    def _candidates(self, public_id: str) -> list[str]:
        values = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    values.append(f"{provider_id}/{capability_id}")
        return values

    def test_shared_temperature_forecast_intent_has_six_candidates(self) -> None:
        self.assertEqual(
            self._candidates("weather.point.temperature"),
            [
                "open_meteo/temperature",
                "met_norway/temperature",
                "noaa_nws/temperature",
                "fmi/temperature",
                "smhi/temperature",
                "jma/temperature",
            ],
        )
        meta = self.mapping["public_capabilities"]["weather.point.temperature"]
        contract = meta["intent_contract"]
        self.assertEqual(contract["kind"], "numeric_point")
        self.assertEqual(contract["canonical_unit"], "°C")
        self.assertEqual(contract["quantity_policy"], "air_temperature")
        self.assertEqual(contract["observation_kind_policy"], "forecast")
        self.assertTrue(contract["numeric_interchangeable"])

    def test_eccc_temperature_is_separate_observation(self) -> None:
        self.assertEqual(
            self._candidates("weather.observation.temperature"),
            ["eccc_geomet/temperature"],
        )
        self.assertNotIn(
            "eccc_geomet/temperature",
            self._candidates("weather.point.temperature"),
        )
        meta = self.mapping["public_capabilities"]["weather.observation.temperature"]
        contract = meta["intent_contract"]
        self.assertEqual(contract["observation_kind_policy"], "observation")
        self.assertEqual(contract["quantity_policy"], "air_temperature")
        self.assertEqual(contract["canonical_unit"], "°C")

    def test_specialized_temperature_paths_are_preserved(self) -> None:
        self.assertEqual(
            self._candidates("weather.nowcast.temperature"),
            ["met_norway/nowcast_temperature"],
        )
        self.assertEqual(
            self._candidates("weather.model.temperature_2m.layer"),
            ["dwd/icon_temperature_2m"],
        )
        self.assertEqual(
            self._candidates("weather.satellite.fire_temperature.goes_east"),
            ["nasa_gibs/satellite_goes_east_fire_temperature"],
        )
        self.assertEqual(
            self._candidates("weather.satellite.fire_temperature.goes_west"),
            ["nasa_gibs/satellite_goes_west_fire_temperature"],
        )

    def test_runtime_public_capability_count_is_226(self) -> None:
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)

    def test_dwd_global_icon_grid_contract_requires_runtime_layer_presence(self) -> None:
        source = (
            ROOT
            / "custom_components"
            / "weather_router"
            / "providers"
            / "dwd.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"Icon_reg025_fd_sl_T2M"', source)
        self.assertIn('"Icon_reg025_fd_sl_UV10M"', source)
        self.assertIn("def _documented_icon_global_grid_coverage(", source)
        self.assertIn('"scope": "global"', source)
        self.assertIn(
            '"source": "dwd_official_model_grid_contract"',
            source,
        )
        self.assertIn("runtime_layer_presence_verified", source)
        self.assertIn('item.get("target_present") is True', source)
        self.assertIn("endpoint_reachability_is_coverage", source)

    def test_routing_diagnostic_git_export_rejects_stale_manual_selection(self) -> None:
        source = (
            ROOT
            / "custom_components"
            / "weather_router"
            / "frontend"
            / "weather-router-lab-routing-diagnostics.js"
        ).read_text(encoding="utf-8")
        self.assertIn("manualCapability!==traceCapability", source)
        self.assertIn("Erst „Resolve testen“ ausführen.", source)
        self.assertIn(
            'state.exportMessage="Aktueller Resolve noch nicht nach Git übertragen."',
            source,
        )

    def test_dwd_coverage_has_canonical_global_wms_fallback(self) -> None:
        source = (
            ROOT
            / "custom_components"
            / "weather_router"
            / "providers"
            / "dwd.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '_PRIMARY_GLOBAL_WMS = "https://maps.dwd.de/geoserver/ows"',
            source,
        )
        self.assertIn(
            '_BACKUP_GLOBAL_WMS = "https://brz-maps.dwd.de/geoserver/ows"',
            source,
        )
        self.assertIn("async def _async_global_wms_coverage(", source)
        self.assertIn("global_wms_get_capabilities", source)
        self.assertIn("target_present", source)
        self.assertIn("fallbacks:", source)

    def test_dwd_layer_coverage_uses_layer_scoped_wms_endpoint(self) -> None:
        source = (
            ROOT
            / "custom_components"
            / "weather_router"
            / "providers"
            / "dwd.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'scoped_path = f"{path}/{quote(layer, safe=\'\')}/wms"',
            source,
        )
        self.assertNotIn(
            'scoped_path = f"{path}/{quote(layer, safe=\'\')}/ows"',
            source,
        )

    def test_provider_priority_is_not_added(self) -> None:
        raw = MAP_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("provider_priority", raw)


if __name__ == "__main__":
    unittest.main()
