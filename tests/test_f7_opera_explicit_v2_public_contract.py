"""Public no-secret regression against the mirrored original V2 contract.

No original weather data, geographical user positions or private extension code.
"""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "custom_components/weather_router/raster_mosaic_contract.py"
spec = importlib.util.spec_from_file_location("f7_public_real_v2_contract", SOURCE)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)

def request():
    return {
        "type": "weather_router/consumer/resolve_mosaic",
        "contract_version": 2,
        "capability": "weather.precipitation.layer",
        "context": {"type": "bbox", "west": 8, "south": 48, "east": 12, "north": 55},
        "time": {"mode": "latest_coherent", "max_data_age_seconds": 900},
        "limits": {"max_layers": 3, "max_tile_requests": 64},
        "consumer_id": "synthetic-test",
        "correlation_id": "public-opera-synthetic-test",
    }

class ExplicitOperaContractTests(unittest.TestCase):
    def test_automatic_route_unchanged(self):
        normal = contract.validate_raster_mosaic_request(request())
        self.assertNotIn("source_request", normal)

    def test_explicit_opera_rate(self):
        raw = request()
        raw["source_request"] = {"provider_id":"opera","product_id":"RATE"}
        actual = contract.validate_raster_mosaic_request(raw)
        self.assertEqual(actual["source_request"],raw["source_request"])

    def test_unapproved_products_and_provider_lists(self):
        for source in (
            {"provider_id":"dwd","product_id":"RATE"},
            {"provider_id":"opera","product_id":"DBZH"},
            {"provider_id":"opera","product_id":"RATE","enabled":True},
            {"provider_id":"opera","product_id":["RATE"]},
            {},
        ):
            raw=request()
            raw["source_request"]=source
            with self.subTest(source=str(source)), self.assertRaises((contract.MosaicContractError,TypeError,ValueError)):
                contract.validate_raster_mosaic_request(raw)
        raw=request()
        raw["providers"]=["opera","dwd"]
        with self.assertRaises(contract.MosaicContractError):
            contract.validate_raster_mosaic_request(raw)

    def test_opera_900_second_limit_only(self):
        raw=request()
        raw["source_request"]={"provider_id":"opera","product_id":"RATE"}
        raw["time"]["max_data_age_seconds"]=901
        with self.assertRaises(contract.MosaicContractError):
            contract.validate_raster_mosaic_request(raw)
        del raw["source_request"]
        self.assertEqual(contract.validate_raster_mosaic_request(raw)["time"]["max_data_age_seconds"],901)

if __name__=="__main__":
    unittest.main()
