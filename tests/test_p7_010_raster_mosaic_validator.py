"""P7-010 pure opt-in V2 request validator. No Home Assistant/network required."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "custom_components/weather_router/raster_mosaic_contract.py"
SPEC = importlib.util.spec_from_file_location("wr_p7_mosaic_contract", PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def sample():
    return {
        "type": "weather_router/consumer/resolve_mosaic",
        "contract_version": 2,
        "capability": "weather.precipitation.layer",
        "context": {
            "type": "bbox", "west": -180, "south": -70,
            "east": 180, "north": 70,
            "focus": {"latitude": 18, "longitude": -77},
        },
        "time": {"mode": "latest_coherent", "max_data_age_seconds": 900,
                 "max_time_delta_seconds": 120},
        "limits": {"max_layers": 4, "max_tile_requests": 48},
    }


class MosaicValidatorTests(unittest.TestCase):
    def test_complete_world_and_true_focus(self):
        result = module.validate_raster_mosaic_request(sample())
        self.assertEqual(result["context"]["west"], -180)
        self.assertEqual(result["context"]["east"], 180)
        self.assertEqual(result["context"]["focus"]["longitude"], -77)
        self.assertEqual(result["time"]["max_data_age_seconds"], 900)

    def test_antimeridian(self):
        request = sample()
        request["context"].update(west=170, east=-170)
        self.assertEqual(module.validate_raster_mosaic_request(request)["context"]["west"], 170)

    def test_explicit_v2_not_silent_v1(self):
        request = sample()
        request["contract_version"] = 1
        with self.assertRaises(module.MosaicContractError):
            module.validate_raster_mosaic_request(request)

    def test_no_unbounded_load(self):
        request = sample()
        request["limits"]["max_layers"] = 999
        with self.assertRaises(module.MosaicContractError):
            module.validate_raster_mosaic_request(request)

    def test_timezone_required_for_specific_time(self):
        request = sample()
        request["time"] = {"mode": "at_time", "max_data_age_seconds": 900,
                           "target_time": "2026-10-14T14:00:00"}
        with self.assertRaises(module.MosaicContractError):
            module.validate_raster_mosaic_request(request)
        request["time"]["target_time"] += "Z"
        self.assertEqual(module.validate_raster_mosaic_request(request)["time"]["mode"], "at_time")

    def test_boolean_coordinates_rejected(self):
        request = sample()
        request["context"]["west"] = True
        with self.assertRaises(module.MosaicContractError):
            module.validate_raster_mosaic_request(request)

    def test_unknown_fields_rejected(self):
        request = sample()
        request["preferred_provider"] = "hardcoded"
        with self.assertRaises(module.MosaicContractError):
            module.validate_raster_mosaic_request(request)


if __name__ == "__main__":
    unittest.main()
