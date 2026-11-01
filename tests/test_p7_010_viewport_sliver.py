"""P7-010 reproducible regression case: tiny Germany edge beats global rain."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components/weather_router"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


spatial = load("wr_spatial_edge_p7", PKG / "spatial_coverage.py")
semantic = load("wr_semantic_edge_p7", PKG / "consumer_routing_policy.py")
prototype = load("wr_viewport_proto_p7", PKG / "raster_viewport_policy.py")
mapping = json.loads((PKG / "consumer_capability_map.json").read_text(encoding="utf-8"))
CUBA_TO_GERMANY = {
    "type": "bbox", "west": -90.0, "south": 15.0,
    "east": 8.0, "north": 56.0,
}
DWD_LIKE = {
    "scope": "bbox",
    "bbox": {"west": 5.0, "south": 46.0, "east": 16.0, "north": 56.0},
}
BROAD_LIKE = {"scope": "global"}
DWD_FOCUSED = {
    "type": "bbox", "west": 6.0, "south": 47.0,
    "east": 12.0, "north": 54.0,
}


def score(key: str):
    return semantic.candidate_score(
        mapping, "weather.precipitation.layer", mapping["candidate_semantics"][key]
    )


class ViewportSliverRegression(unittest.TestCase):
    def test_existing_routing_mistakes_tiny_sliver_for_eligible_coverage(self):
        # Reproduces the confirmed underlying weakness without altering runtime.
        self.assertTrue(spatial.coverage_matches_context(DWD_LIKE, CUBA_TO_GERMANY))
        d = spatial.coverage_diagnostics(DWD_LIKE, CUBA_TO_GERMANY)
        self.assertTrue(d["routing_match"])
        self.assertFalse(d["center_inside"])
        self.assertGreater(d["overlap_percent"], 0)
        self.assertLess(d["overlap_percent"], 1.0)

    def test_original_semantic_rank_prefers_dwd_over_nasa(self):
        self.assertLess(
            score("dwd/radar_precipitation_quality_checked"),
            score("nasa_gibs/satellite_precipitation_imerg_30min"),
        )
        # These two facts in the current single-winner pipeline explain why
        # a tiny DWD coverage sliver can displace the wider satellite view.

    def test_prototype_prefers_broad_source_when_germany_only_touches_edge(self):
        d = spatial.coverage_diagnostics(DWD_LIKE, CUBA_TO_GERMANY)
        broad = spatial.coverage_diagnostics(BROAD_LIKE, CUBA_TO_GERMANY)
        self.assertLess(
            prototype.experimental_viewport_rank(
                broad, score("nasa_gibs/satellite_precipitation_imerg_30min")
            ),
            prototype.experimental_viewport_rank(
                d, score("dwd/radar_precipitation_quality_checked")
            ),
        )

    def test_prototype_keeps_local_radar_for_german_viewpoint(self):
        d = spatial.coverage_diagnostics(DWD_LIKE, DWD_FOCUSED)
        broad = spatial.coverage_diagnostics(BROAD_LIKE, DWD_FOCUSED)
        self.assertEqual(d["overlap_percent"], 100.0)
        self.assertTrue(d["center_inside"])
        self.assertLess(
            prototype.experimental_viewport_rank(
                d, score("dwd/radar_precipitation_quality_checked")
            ),
            prototype.experimental_viewport_rank(
                broad, score("nasa_gibs/satellite_precipitation_imerg_30min")
            ),
        )

    def test_antimeridian_uses_wr_existing_normalized_coverage(self):
        request = {
            "type": "bbox", "west": 160.0, "east": -160.0,
            "south": -10.0, "north": 10.0,
        }
        local = {
            "scope": "bbox",
            "bbox": {"west": 170.0, "east": -175.0, "south": -5.0, "north": 5.0},
        }
        d = spatial.coverage_diagnostics(local, request)
        self.assertTrue(d["routing_match"])
        self.assertGreater(d["overlap_percent"], 0)
        self.assertIsNotNone(
            prototype.experimental_viewport_rank(d, (0, 0, 0))
        )

    def test_no_coverage_and_invalid_numbers_fail_closed(self):
        outside = spatial.coverage_diagnostics(DWD_LIKE, {
            "type": "bbox", "west": -90.0, "east": -70.0,
            "south": 10.0, "north": 25.0,
        })
        self.assertIsNone(prototype.experimental_viewport_rank(outside, (0, 0, 0)))
        self.assertIsNone(prototype.experimental_viewport_rank({
            "routing_match": True, "center_inside": False,
            "overlap_percent": float("nan")
        }, (0, 0, 0)))
        self.assertIsNone(prototype.experimental_viewport_rank({
            "routing_match": True, "center_inside": False,
            "overlap_percent": None
        }, (0, 0, 0)))


if __name__ == "__main__":
    unittest.main()
