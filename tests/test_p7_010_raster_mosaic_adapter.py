"""Pure P7-010 candidate adapter contract tests, no HA or provider contact."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

PATH = (Path(__file__).resolve().parents[1]
        / "custom_components/weather_router/raster_mosaic_adapter.py")
SPEC = importlib.util.spec_from_file_location("wr_p7_mosaic_adapter", PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

SEM = {
    "quantity": "precipitation_rate",
    "unit": "mm/h",
    "measurement_method": "radar",
    "observation_kind": "observation",
}
REGION = {"scope": "bbox",
          "bbox": {"west": 5, "south": 46, "east": 16, "north": 56}}
PUBLIC_RESOURCE = {
    "tile_url": "https://example.invalid/wms/{z}/{x}/{y}.png",
    "attribution": "Provider mit Quellenangabe",
    "legend": {"title": "Niederschlag"},
}


def candidate(**kwargs):
    p = {
        "source_id": "provider/capability",
        "eligible": True,
        "machine_coverage": REGION,
        "payload": PUBLIC_RESOURCE,
        "semantics": SEM,
        "data_time": "2026-10-14T15:00:00Z",
        "retrieved_at": "2026-10-14T15:08:00Z",
    }
    p.update(kwargs)
    return mod.make_mosaic_candidate(**p)


class AdapterTests(unittest.TestCase):
    def test_region_preserved_not_expanded(self):
        result = candidate()
        self.assertEqual(result["coverage"]["scope"], "bbox")
        self.assertEqual(result["coverage"]["bbox"]["west"], 5)
        self.assertEqual(result["data_time"], "2026-10-14T15:00:00Z")
        self.assertTrue(result["verified_coverage"])

    def test_global_must_be_verified_explicitly(self):
        result = candidate(machine_coverage={"scope": "global"})
        self.assertEqual(result["coverage"], {"scope": "global"})
        self.assertIsNone(candidate(machine_coverage=None))
        self.assertIsNone(candidate(machine_coverage={"scope": "unknown"}))

    def test_global_disabled_remains_disabled(self):
        self.assertIsNone(candidate(eligible=False))

    def test_invalid_bboxes_do_not_become_global(self):
        b = dict(REGION["bbox"])
        b["east"] = 300
        self.assertIsNone(candidate(machine_coverage={"scope": "bbox", "bbox": b}))
        b["east"] = 5
        self.assertIsNone(candidate(machine_coverage={"scope": "bbox", "bbox": b}))

    def test_denied_or_unknown_semantics_fail_closed(self):
        sem = dict(SEM)
        sem.pop("measurement_method")
        self.assertIsNone(candidate(semantics=sem))
        self.assertIsNone(candidate(payload={**PUBLIC_RESOURCE, "legend": None}))

    def test_unsafe_url_rejected(self):
        bad = dict(PUBLIC_RESOURCE)
        bad["tile_url"] = "http://example.invalid/raster"
        self.assertIsNone(candidate(payload=bad))
        bad["tile_url"] = "https://example.invalid/tiles?token=secret-value"
        self.assertIsNone(candidate(payload=bad))
        bad["tile_url"] = "https://user:pass@example.invalid/tiles"
        self.assertIsNone(candidate(payload=bad))
        bad["tile_url"] = "https://example.invalid/tiles#private"
        self.assertIsNone(candidate(payload=bad))

    def test_native_tile_render_parameters_survive(self):
        raw = {**PUBLIC_RESOURCE, "tile_size": 512, "min_zoom": 3,
               "max_zoom": 14, "default_opacity": 0.65}
        result = candidate(payload=raw)
        self.assertEqual(result["render"], {
            "tile_size": 512, "min_zoom": 3.0,
            "max_zoom": 14.0, "opacity": 0.65,
        })

    def test_invalid_native_tile_parameters_fail_closed(self):
        for override in (
            {"tile_size": 4096},
            {"tile_size": True},
            {"min_zoom": 17, "max_zoom": 13},
            {"default_opacity": -0.1},
            {"default_opacity": 1.2},
            {"max_zoom": float("nan")},
        ):
            with self.subTest(override=override):
                self.assertIsNone(candidate(payload={**PUBLIC_RESOURCE, **override}))

    def test_multiple_frames_retained_separately(self):
        payload = {**PUBLIC_RESOURCE, "timeline": {
            "frames": [
                {"time": "2026-10-14T15:01:00Z",
                 "tile_url": "https://example.invalid/one"},
                {"time": "2026-10-14T15:03:00Z",
                 "tile_url": "https://example.invalid/two"},
            ]
        }}
        result = candidate(payload=payload)
        self.assertEqual(len(result["frames"]), 2)
        self.assertEqual(result["frames"][0]["data_time"],
                         "2026-10-14T15:03:00Z")
        self.assertNotEqual(result["frames"][0]["tile_url"], result["frames"][1]["tile_url"])

    def test_dwd_long_timeline_selects_bounded_newest_frames(self):
        from datetime import datetime, timedelta, timezone
        start = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)
        frames = [
            {"time": (start + timedelta(minutes=i)).isoformat(),
             "tile_url": f"https://example.invalid/frame/{i}"} for i in range(48)
        ]
        payload = {**PUBLIC_RESOURCE, "timeline": {"frames": frames}}
        result = candidate(payload=payload)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["frames"]), 24)
        self.assertEqual(result["frames"][0]["tile_url"], "https://example.invalid/frame/47")
        self.assertEqual(result["frames"][-1]["tile_url"], "https://example.invalid/frame/24")

    def test_excessive_unbounded_timeline_rejected(self):
        frame = {"time": "2026-10-14T15:01:00Z",
                 "tile_url": "https://example.invalid/raster"}
        self.assertIsNone(candidate(payload={
            **PUBLIC_RESOURCE, "timeline": {"frames": [frame] * 257}
        }))


if __name__ == "__main__":
    unittest.main()
