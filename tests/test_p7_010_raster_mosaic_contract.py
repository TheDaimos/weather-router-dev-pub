"""Static P7-010 multi-provider raster contract regression; no HA/provider calls."""
from __future__ import annotations
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts/p7_010/raster_mosaic.response.v2.proposal.schema.json"


class MosaicSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_request_is_opt_in_and_explicitly_bounded(self):
        request = json.loads((ROOT / "contracts/p7_010/raster_mosaic.request.v2.proposal.schema.json")
                             .read_text(encoding="utf-8"))
        fields = request["properties"]
        self.assertEqual(fields["contract_version"]["const"], 2)
        self.assertEqual(fields["type"]["const"], "weather_router/consumer/resolve_mosaic")
        self.assertIn("focus", fields["context"]["properties"])
        self.assertEqual(fields["context"]["properties"]["focus"]["type"], "object")
        time_fields = fields["time"]["properties"]
        self.assertIn("max_data_age_seconds", fields["time"]["required"])
        self.assertIn("latest_coherent", time_fields["mode"]["enum"])
        self.assertIn("target_time", time_fields)
        self.assertGreater(fields["limits"]["properties"]["max_layers"]["maximum"], 3)
        self.assertIn("max_tile_requests", fields["limits"]["required"])

    def test_v1_is_not_repurposed(self):
        self.assertEqual(self.schema["properties"]["contract_version"]["const"], 2)
        self.assertEqual(self.schema["properties"]["capability"]["const"], "weather.precipitation.layer")

    def test_multiple_sources_not_provider_hardcoded(self):
        layers = self.schema["properties"]["layers"]
        self.assertEqual(layers["type"], "array")
        self.assertGreaterEqual(layers["maxItems"], 4)
        source = self.schema["$defs"]["layer"]["properties"]["source_id"]
        self.assertNotIn("enum", source)
        self.assertNotIn("const", source)

    def test_each_source_keeps_coverage_and_time_and_semantics(self):
        layer = self.schema["$defs"]["layer"]
        self.assertTrue({"coverage", "times", "semantics", "legend", "attribution"}.issubset(layer["required"]))
        self.assertTrue({"quantity", "unit", "measurement_method", "observation_kind"}.issubset(
            layer["properties"]["semantics"]["required"]))
        self.assertTrue({"valid_at", "retrieved_at"}.issubset(layer["properties"]["times"]["required"]))
        self.assertIn("null", layer["properties"]["times"]["properties"]["valid_at"]["type"])
        self.assertIn("reference_delta_seconds", layer["properties"]["times"]["properties"])

    def test_partial_data_and_antimeridian_possible(self):
        self.assertIn("partial", self.schema["properties"]["status"]["enum"])
        bbox = self.schema["$defs"]["bbox"]["properties"]
        self.assertEqual(bbox["west"]["minimum"], -180)
        self.assertEqual(bbox["east"]["maximum"], 180)
        self.assertEqual(bbox["south"]["minimum"], -90)
        self.assertEqual(bbox["north"]["maximum"], 90)
        self.assertIn("uncovered_regions", self.schema["properties"])


if __name__ == "__main__":
    unittest.main()
