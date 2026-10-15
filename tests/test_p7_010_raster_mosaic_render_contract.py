"""P7-010: V2 render contract shared with Gewitterradar (pure/no HA).
The live WebSocket endpoint still needs a Home Assistant real acceptance run.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components" / "weather_router"


def load(name: str):
    spec = importlib.util.spec_from_file_location(
        "p7_render_" + name, PKG / (name + ".py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load("raster_mosaic_adapter")
policy = load("raster_mosaic_policy")
SCHEMA = json.loads(
    (ROOT / "contracts/p7_010/raster_mosaic.response.v2.proposal.schema.json")
    .read_text(encoding="utf-8")
)
NOW = "2026-10-15T07:00:00Z"
SEMANTICS = {
    "quantity": "precipitation_rate", "unit": "mm/h",
    "measurement_method": "satellite_estimate",
    "observation_kind": "observation",
}
COVERAGE = {"scope": "global"}
VIEWPORT = {"west": -90, "south": 15, "east": 8, "north": 56}


class V2RenderTests(unittest.TestCase):
    def _candidate(self, payload=None):
        return adapter.make_mosaic_candidate(
            source_id="synthetic_public_source",
            eligible=True, machine_coverage=COVERAGE,
            payload=payload or {
                "tile_url": "https://example.invalid/{z}/{x}/{y}.png",
                "attribution": "Public example", "legend": {"title": "Rain"},
                "tile_size": 512, "min_zoom": 1,
                "max_zoom": 14, "default_opacity": 0.65,
            },
            semantics=SEMANTICS, data_time="2026-10-15T06:59:00Z",
            retrieved_at=NOW,
        )

    def test_active_consumer_required_render_fields(self):
        candidate = self._candidate()
        self.assertIsNotNone(candidate)
        answer = policy.plan_raster_mosaic(
            [candidate], viewport=VIEWPORT, now=NOW,
            max_data_age_seconds=900, max_time_delta_seconds=180,
            max_layers=4,
        )
        self.assertEqual(answer["status"], "partial")
        self.assertEqual(len(answer["layers"]), 1)
        layer = answer["layers"][0]
        self.assertEqual(layer["render"], {
            "tile_size": 512, "min_zoom": 1.0,
            "max_zoom": 14.0, "opacity": 0.65,
        })
        contract = SCHEMA["$defs"]["layer"]
        self.assertTrue(set(contract["required"]).issubset(layer))
        self.assertTrue(set(contract["properties"]).issuperset(layer))
        self.assertEqual(
            set(contract["properties"]["render"]["required"]),
            set(layer["render"]),
        )

    def test_invalid_render_metadata_fails_closed(self):
        payload = {
            "tile_url": "https://example.invalid/{z}/{x}/{y}.png",
            "attribution": "Public example", "legend": {"title": "Rain"},
            "tile_size": 1024,
        }
        self.assertIsNone(self._candidate(payload))
        payload["tile_size"] = 256
        payload["max_zoom"] = 25
        self.assertIsNone(self._candidate(payload))
        payload["max_zoom"] = 18
        payload["default_opacity"] = 2
        self.assertIsNone(self._candidate(payload))

    def test_client_does_not_accept_unbounded_layers(self):
        candidates = []
        for i in range(8):
            source = self._candidate()
            source["source_id"] = "synthetic_" + str(i)
            candidates.append(source)
        answer = policy.plan_raster_mosaic(
            candidates, viewport=VIEWPORT, now=NOW,
            max_data_age_seconds=900, max_time_delta_seconds=180,
            max_layers=4,
        )
        self.assertEqual(len(answer["layers"]), 4)
        self.assertTrue(any("Ressourcenbegrenzung" in line
                            for line in answer["limitations"]))


if __name__ == "__main__":
    unittest.main()
