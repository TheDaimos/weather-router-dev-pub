"""Regression for the real F10/F11 module import and cache interface.

No network access, HA imports or external pixels needed. Raster rendering
is separately gated on installed GDAL/Pillow in the eventual HA environment.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import importlib.util
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "weather_router"
PACKAGE = "_wr_opera_standalone_test"
if PACKAGE not in sys.modules:
    pkg = types.ModuleType(PACKAGE)
    pkg.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = pkg

def load(name):
    name_full = PACKAGE + "." + name
    if name_full not in sys.modules:
        spec = importlib.util.spec_from_file_location(name_full, ROOT / (name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name_full] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name_full]

cache_lib = load("opera_frame_cache")
tiles = load("opera_cog_tiles")

class OperaRenderCacheContract(unittest.TestCase):
    def setUp(self):
        self.cache = cache_lib.ImmutableFrameCache(max_frames=2)
        self.temporary = tempfile.TemporaryDirectory()
        self.frame_time = datetime(2026, 10, 19, 13, 40, tzinfo=timezone.utc)

    def tearDown(self):
        self.cache.close()
        self.temporary.cleanup()

    def test_revision_identity_and_freshness_independent(self):
        key = dict(product="DBZH",source_time=self.frame_time,z=6,x=33,y=19,
                   palette_rev="v1",quality_rev="unchecked")
        a = tiles.immutable_key(source_sha256="a"*64, **key)
        b = tiles.immutable_key(source_sha256="b"*64, **key)
        self.assertNotEqual(a, b)
        tiles.authorize_current(self.frame_time, self.frame_time+timedelta(seconds=900))
        with self.assertRaises(tiles.OperaRasterError):
            tiles.authorize_current(self.frame_time, self.frame_time+timedelta(seconds=901))
        self.assertEqual(a, tiles.immutable_key(source_sha256="a"*64, **key))

    def test_verified_frame_type_and_no_second_hash(self):
        source = Path(self.temporary.name) / "trusted.tiff"
        source.write_bytes(b"immutable frame fixture")
        expected = hashlib.sha256(source.read_bytes()).hexdigest()
        frame = self.cache.admit(source_path=source,product="DBZH",
                                valid_at=self.frame_time, expected_sha256=expected)
        self.assertIsInstance(frame, cache_lib.VerifiedFrame)
        self.assertEqual(self.cache.hash_operations,1)
        self.assertIs(frame,self.cache.get(product="DBZH",
                                          valid_at=self.frame_time,digest=expected))
        self.assertIs(frame,self.cache.admit(source_path=source,product="DBZH",
                                            valid_at=self.frame_time,expected_sha256=expected))
        self.assertEqual(self.cache.hash_operations,1)

    def test_both_products_separate_identity(self):
        for product in ("DBZH","RATE"):
            fixture=Path(self.temporary.name)/(product+".tiff")
            fixture.write_bytes(product.encode())
            digest=hashlib.sha256(product.encode()).hexdigest()
            frame=self.cache.admit(source_path=fixture,product=product,
                                   valid_at=self.frame_time,expected_sha256=digest)
            self.assertEqual(frame.product,product)

if __name__ == "__main__":
    unittest.main()
