"""P7-010: audit public precipitation provider implementations without network.

Records contract-ready providers as an implementation fact, not as proof of
live data coverage. In particular a display-text coverage statement must
never be treated as machine-readable geographic coverage.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/weather_router"
MAP = json.loads((ROOT / "consumer_capability_map.json").read_text(encoding="utf-8"))
PUBLIC_ID = "weather.precipitation.layer"


def methods_for(module_name: str) -> dict[str, set[str]]:
    path = ROOT / "providers" / (module_name + ".py")
    if not path.is_file():
        return {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name: {
            method.name for method in node.body
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
        } for node in tree.body if isinstance(node, ast.ClassDef)
    }


class ReadinessInventoryTests(unittest.TestCase):
    def test_mapped_precipitation_provider_readiness_is_explicit(self):
        candidates = [
            (provider_id, internal_id)
            for provider_id, rows in MAP["providers"].items()
            for internal_id, public_ids in rows.items()
            if PUBLIC_ID in public_ids
        ]
        self.assertGreaterEqual(len(candidates), 5)
        known_without_machine_coverage = []
        with_machine_coverage = []
        for provider_id, internal_id in candidates:
            methods = set().union(*methods_for(provider_id).values())
            self.assertIn("async_get_map_layer", methods, provider_id)
            if "async_get_coverage" not in methods:
                known_without_machine_coverage.append((provider_id, internal_id))
            else:
                with_machine_coverage.append((provider_id, internal_id))
        # The V2 endpoint must not silently treat a human-readable description
        # such as "international radar" as guaranteed geographic coverage.
        self.assertIn(("rainviewer", "radar_reflectivity"),
                      known_without_machine_coverage)
        self.assertGreaterEqual(len(with_machine_coverage), 4)
        self.assertIn(("nasa_gibs", "satellite_precipitation_imerg_30min"),
                      with_machine_coverage)

    def test_v2_endpoint_requires_real_provider_coverage_method(self):
        endpoint = (ROOT / "consumer_raster_mosaic_api.py").read_text(encoding="utf-8")
        self.assertIn('callable(getattr(row.provider, "async_get_coverage", None))',
                      endpoint)
        self.assertIn("normalize_coverage(coverage_raw)", endpoint)
        self.assertNotIn("provider_info().coverage", endpoint)


if __name__ == "__main__":
    unittest.main()
