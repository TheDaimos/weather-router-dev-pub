"""Public-only Python regression: WR V2 authority contract, no private checkout."""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "wr_public_mosaic_contract",
    ROOT / "custom_components/weather_router/raster_mosaic_contract.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def request():
    return {
        "type": "weather_router/consumer/resolve_mosaic",
        "contract_version": 2,
        "capability": "weather.precipitation.layer",
        "context": {"type": "bbox", "west": 8, "east": 12, "south": 48, "north": 55},
        "time": {"mode": "latest_coherent", "allow_older_satellite_background": False},
        "limits": {"max_layers": 3, "max_tile_requests": 64},
    }


class WRPublicAuthorityTests(unittest.TestCase):
    def test_client_does_not_supply_own_age(self):
        parsed = module.validate_raster_mosaic_request(request())
        self.assertNotIn("max_data_age_seconds", parsed["time"])
        self.assertIs(parsed["time"]["allow_older_satellite_background"], False)

    def test_user_preference_must_be_boolean(self):
        raw = request()
        raw["time"]["allow_older_satellite_background"] = 900
        with self.assertRaises(module.MosaicContractError):
            module.validate_raster_mosaic_request(raw)

    def test_legacy_age_is_not_hard_capped_to_900(self):
        raw = request()
        raw["time"]["max_data_age_seconds"] = 1650
        raw["source_request"] = {"provider_id": "opera", "product_id": "RATE"}
        parsed = module.validate_raster_mosaic_request(raw)
        self.assertEqual(parsed["time"]["max_data_age_seconds"], 1650)

    def test_untrusted_source_list_rejected(self):
        raw = request()
        raw["providers"] = ["opera"]
        with self.assertRaises(module.MosaicContractError):
            module.validate_raster_mosaic_request(raw)


if __name__ == "__main__":
    unittest.main()
