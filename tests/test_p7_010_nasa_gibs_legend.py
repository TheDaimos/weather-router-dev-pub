"""P7-010: WMS layers without a legend URL keep honest descriptive metadata.

This checks the actual NASA provider branch and the public V2 adapter without
requesting WMS data or inventing an unknown precipitation/colour conversion.
"""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/weather_router"


def load_module(name: str):
    path = ROOT / (name + ".py")
    spec = importlib.util.spec_from_file_location(name + "_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GibsLegendFallbackTest(unittest.TestCase):
    def test_provider_always_constructs_a_descriptive_legend(self):
        source = (ROOT / "providers/nasa_gibs.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        provider_methods = [
            item for klass in tree.body if isinstance(klass, ast.ClassDef)
            for item in klass.body if isinstance(item, ast.AsyncFunctionDef)
            and item.name == "async_get_map_layer"
        ]
        self.assertEqual(len(provider_methods), 1)
        method = provider_methods[0]
        top_level_assignments = [
            item for item in method.body
            if isinstance(item, ast.Assign)
            and any(isinstance(t, ast.Subscript)
                    and isinstance(t.value, ast.Name)
                    and t.value.id == "descriptor"
                    and isinstance(t.slice, ast.Constant)
                    and t.slice.value == "legend"
                    for t in item.targets)
        ]
        self.assertEqual(len(top_level_assignments), 1,
                         "description must not depend on optional legend URL")
        fields = top_level_assignments[0].value
        self.assertIsInstance(fields, ast.Dict)
        keys = {x.value for x in fields.keys if isinstance(x, ast.Constant)}
        self.assertEqual(keys, {"title", "style"})
        self.assertNotIn("dBZ", ast.get_source_segment(source, top_level_assignments[0]) or "")

    def test_title_only_legend_is_valid_with_real_nullable_unit(self):
        metadata = json.loads(
            (ROOT / "consumer_capability_map.json").read_text(encoding="utf-8")
        )
        semantics = metadata["candidate_semantics"][
            "nasa_gibs/satellite_precipitation_imerg_30min"
        ]
        adapter = load_module("raster_mosaic_adapter")
        candidate = adapter.make_mosaic_candidate(
            source_id="nasa_gibs/satellite_precipitation_imerg_30min",
            eligible=True,
            machine_coverage={"scope": "global"},
            payload={
                "tile_url": "https://example.invalid/{z}/{x}/{y}.png",
                "tile_size": 256,
                "max_zoom": 9,
                "attribution": "NASA EOSDIS GIBS",
                "legend": {"title": "NASA GIBS · IMERG", "style": None},
            },
            semantics=semantics,
            data_time="2026-10-14T15:00:00Z",
            retrieved_at="2026-10-14T15:04:00Z",
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["legend"]["title"], "NASA GIBS · IMERG")
        self.assertEqual(candidate["render"]["max_zoom"], 9.0)


if __name__ == "__main__":
    unittest.main()
