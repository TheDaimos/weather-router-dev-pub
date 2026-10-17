"""Isolated regression of actual provider UTC parsers without Home Assistant."""
from __future__ import annotations
import ast
from datetime import datetime, timezone
import importlib
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/weather_router"
ROOT_PKG = "wr_p7010_utc_parser"
if ROOT_PKG not in sys.modules:
    pkg = types.ModuleType(ROOT_PKG)
    pkg.__path__ = [str(ROOT)]
    sys.modules[ROOT_PKG] = pkg
    providers = types.ModuleType(ROOT_PKG + ".providers")
    providers.__path__ = [str(ROOT / "providers")]
    sys.modules[ROOT_PKG + ".providers"] = providers


def extracted(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    target = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == name)
    package = ROOT_PKG + ".providers" if "providers" in path.parts else ROOT_PKG
    namespace = {"__name__": package + ".test_isolated",
                 "__package__": package,
                 "datetime": datetime, "timezone": timezone}
    module = ast.fix_missing_locations(ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
              target], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


class ProviderUtcPathTests(unittest.TestCase):
    def test_consumer_central_parser_no_numeric_guess(self):
        func = extracted(ROOT / "consumer_api.py", "_iso_time")
        self.assertEqual(func("2026-10-16T14:00:00+02:00"),
                         "2026-10-16T12:00:00Z")
        self.assertIsNone(func("2026-10-16T12:00:00"))
        self.assertIsNone(func("bad-time"))
        self.assertIsNone(func(1792152000))
        self.assertEqual(func(1792152000, epoch_unit="seconds"),
                         "2026-10-16T12:00:00Z")
        self.assertEqual(func(1792152000000, epoch_unit="milliseconds"),
                         "2026-10-16T12:00:00Z")

    def test_dwd_wms_epoch_seconds_reach_normalized_v2_raster(self):
        # DWD.async_get_map_layer emits int(timestamp()) for frame_time and
        # timeline[].time. These must be explicitly converted to UTC and not
        # dropped as unknown-unit epochs by the central Consumer V1 sanitizer.
        normalizer = extracted(ROOT / "consumer_api.py", "_normalize_raster")
        normalizer.__globals__.update(
            _iso_time=extracted(ROOT / "consumer_api.py", "_iso_time"),
            _safe_public_url=lambda value: value if isinstance(value, str)
                and value.startswith("https://example.invalid/") else None,
        )
        raw = {
            "provider": "dwd",
            "capability": "radar_precipitation",
            "tile_url": "https://example.invalid/dwd/current",
            "frame_time": 1792152000,
            "attribution": "Synthetic DWD source",
            "legend": {"title": "Rain radar"},
            "timeline": {"frames": [
                {"time": 1792152000,
                 "tile_url": "https://example.invalid/dwd/current"},
                {"time": 1792151700,
                 "tile_url": "https://example.invalid/dwd/previous"},
            ]},
        }
        resource, data_time = normalizer(raw)
        self.assertEqual(data_time, "2026-10-16T12:00:00Z")
        self.assertEqual(
            [frame["time"] for frame in resource["timeline"]["frames"]],
            ["2026-10-16T12:00:00Z", "2026-10-16T11:55:00Z"])
        unknown, undated = normalizer({**raw, "provider": "unknown"})
        self.assertIsNone(undated)
        self.assertEqual(unknown["timeline"]["frames"], [])

    def test_dwd_wms_avoids_naive_utc_guess(self):
        func = extracted(ROOT / "providers/dwd.py", "_parse_instant")
        self.assertIsNone(func("2026-10-16T12:00:00"))
        self.assertIsNone(func("current"))
        self.assertEqual(func("2026-10-16T14:00:00+02:00"),
                         datetime(2026, 10, 16, 12, tzinfo=timezone.utc))

    def test_satellite_current_has_no_fabricated_frame_time(self):
        func = extracted(ROOT / "providers/wms_satellite.py", "_parse_instant")
        self.assertIsNone(func("current", datetime(2026,10,16,tzinfo=timezone.utc)))
        self.assertIsNone(func("2026-10-16T12:00:00", datetime.now(timezone.utc)))
        self.assertEqual(
            func("2026-10-16T14:00:00+02:00", datetime.now(timezone.utc)),
            datetime(2026, 10, 16, 12, tzinfo=timezone.utc))

    def test_jma_requires_source_offset(self):
        func = extracted(ROOT / "providers/jma.py", "_parse_iso_time")
        self.assertIsNone(func("2026-10-16T12:00:00"))
        self.assertEqual(func("2026-10-16T21:00:00+09:00"),
                         datetime(2026, 10, 16, 12, tzinfo=timezone.utc))

    def test_gdacs_invalid_rss_does_not_escape(self):
        func = extracted(ROOT / "providers/gdacs.py", "_rss_time")
        self.assertIsNone(func("invalid"))
        self.assertIsNone(func("Fri, 16 Oct 2026 14:00:00"))
        self.assertEqual(func("Fri, 16 Oct 2026 14:00:00 +0200"),
                         "2026-10-16T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
