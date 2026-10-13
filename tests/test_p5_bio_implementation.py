"""P5-BIO-40: isolated runtime-normalizer tests and GBIF contract checks."""

from __future__ import annotations

import ast
from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROVIDER = (ROOT / "custom_components/weather_router/providers/gbif_biodiversity.py").read_text(encoding="utf-8")
API = (ROOT / "custom_components/weather_router/consumer_api.py").read_text(encoding="utf-8")
CONST = (ROOT / "custom_components/weather_router/const.py").read_text(encoding="utf-8")
LAB = (ROOT / "custom_components/weather_router/frontend/weather-router-lab.js").read_text(encoding="utf-8")
LOADER = (ROOT / "custom_components/weather_router/frontend/weather-router-lab-dev-loader.js").read_text(encoding="utf-8")
MAPPING = json.loads(
    (ROOT / "custom_components/weather_router/consumer_capability_map.json").read_text(encoding="utf-8")
)


def _normalizer():
    """Execute the real generic raster function in isolation, without Home Assistant."""
    module = ast.parse(API)
    method = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_normalize_raster"
    )
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    isolated = ast.Module(body=[future, method], type_ignores=[])
    namespace = {
        "_safe_public_url": lambda value: (
            value if isinstance(value, str) and value.startswith("https://")
            and "secret=" not in value else None
        ),
        "_iso_time": lambda value: value,
    }
    exec(compile(ast.fix_missing_locations(isolated), "<consumer_normalizer>", "exec"), namespace)
    return namespace["_normalize_raster"]


from wr_public_version_contract import assert_current_version_surfaces

class P5BioImplementationTest(unittest.TestCase):
    def test_specialized_provider_and_catalog_are_unchanged(self):
        self.assertEqual(len(MAPPING["public_capabilities"]), 227)
        mapped = MAPPING["providers"]["gbif_biodiversity"]
        self.assertEqual(len(mapped), 88)
        self.assertIn('id = "gbif_biodiversity"', PROVIDER)
        self.assertIn('async def async_get_map_layer(', PROVIDER)
        self.assertIn('result = await fetch(hass, candidate.capability.id)', API)
        self.assertIn('elif mode == "image_sequence":', API)

    def test_real_raster_normalizer_exposes_only_safe_gbif_metadata(self):
        normalize = _normalizer()
        original = {
            "provider": "gbif_biodiversity",
            "tile_url": "https://api.gbif.org/v2/map/occurrence/adhoc/{z}/{x}/{y}@1x.png",
            "attribution": "GBIF.org",
            "tile_size": 256,
            "provider_metadata": {
                "scientific_name_requested": "Panthera leo",
                "scientific_name_matched": "Panthera leo",
                "taxon_key": "5219404",
                "taxon_rank": "SPECIES",
                "taxon_status": "ACCEPTED",
                "match_confidence": 99,
                "from_year": 2000,
                "to_year": 2026,
                "population_density": False,
                "risk_probability": False,
                "warning": "Nur veröffentlichte Vorkommensnachweise; keine aktuelle Gefahrenprognose.",
                "data_user_agreement": "https://www.gbif.org/terms/data-user",
                "private_api_key": "do-not-leak",
                "password": "do-not-leak",
                "arbitrary_url": "https://example.com/?secret=do-not-leak",
            },
        }
        payload, _ = normalize(original)
        self.assertEqual(payload["attribution"], "GBIF.org")
        public = payload["provider_metadata"]
        self.assertEqual(public["scientific_name_requested"], "Panthera leo")
        self.assertEqual(public["taxon_status"], "ACCEPTED")
        self.assertEqual(public["match_confidence"], 99)
        self.assertEqual(public["to_year"], 2026)
        self.assertIs(public["population_density"], False)
        self.assertIs(public["risk_probability"], False)
        self.assertEqual(public["data_user_agreement"], "https://www.gbif.org/terms/data-user")
        self.assertNotIn("private_api_key", public)
        self.assertNotIn("password", public)
        self.assertNotIn("arbitrary_url", public)

    def test_raster_normalizer_does_not_forward_untrusted_metadata_from_other_sources(self):
        normalize = _normalizer()
        payload, _ = normalize({
            "provider": "not_gbif",
            "tile_url": "https://example.com/z/x/y.png",
            "attribution": "Source",
            "provider_metadata": {"secret": "never forward", "warning": "untrusted"},
        })
        self.assertNotIn("provider_metadata", payload)

    def test_untrusted_gbif_terms_url_does_not_escape_allowlist(self):
        normalize = _normalizer()
        payload, _ = normalize({
            "provider": "gbif_biodiversity",
            "tile_url": "https://api.gbif.org/tile",
            "provider_metadata": {
                "scientific_name_matched": "Panthera leo",
                "data_user_agreement": "https://example.com/?secret=token",
                "danger": "do-not-copy",
            },
        })
        self.assertNotIn("data_user_agreement", payload["provider_metadata"])
        self.assertNotIn("danger", payload["provider_metadata"])

    def test_version_synced_for_backend_and_lab(self):
        assert_current_version_surfaces(self, CONST, LAB, LOADER)


if __name__ == "__main__":
    unittest.main()
