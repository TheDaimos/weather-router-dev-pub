"""Independent unit tests for the dormant OPERA tile input policy."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / "custom_components/weather_router/opera_tile_security.py"
spec = importlib.util.spec_from_file_location("opera_tile_security", MODULE)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

class OperaTileSecurityTest(unittest.TestCase):
    def setUp(self):
        self.when = datetime(2026, 10, 19, 13, 40, tzinfo=timezone.utc)
        self.now = self.when + timedelta(minutes=7)

    def test_known_products(self):
        p, frame = policy.frame_id("OPERA@20261019T1340@0@DBZH.tiff", source_time=self.when, now=self.now)
        self.assertEqual((p, frame), ("DBZH", "20261019T134000Z"))
        self.assertEqual(policy.frame_id("OPERA@20261019T1315@0@RATE.tiff",
            source_time=self.when-timedelta(minutes=25),
            now=self.when-timedelta(minutes=18))[0], "RATE")

    def test_invalid_time_and_age(self):
        fn = "OPERA@20261019T1340@0@DBZH.tiff"
        for stamp, now in ((self.when-timedelta(minutes=5), self.now),
                           (self.when, self.when+timedelta(seconds=901)),
                           (self.when, self.when-timedelta(seconds=1))):
            with self.assertRaises(policy.TilePolicyError):
                policy.frame_id(fn, source_time=stamp, now=now)
        with self.assertRaises(policy.TilePolicyError):
            policy.frame_id(fn, source_time=self.when.replace(tzinfo=None), now=self.now)

    def test_bounds(self):
        self.assertEqual(policy.validate_tile(6, 33, 19), (6, 33, 19))
        for item in ((-1,0,0),(17,0,0),(6,64,0),(6,1,-1),("6",33,19),(True,0,0)):
            with self.assertRaises(policy.TilePolicyError):
                policy.validate_tile(*item)

    def test_reject_untrusted_identifiers(self):
        for name in ("../x.tiff", "https://example.net/evil.tiff",
                     "OPERA@20261019T1340@0@RATE.tiff?token=x"):
            with self.assertRaises(policy.TilePolicyError):
                policy.frame_id(name, source_time=self.when, now=self.now)
        with self.assertRaises(policy.TilePolicyError):
            policy.validate_object_size(15*1024*1024)

    def test_time_and_style_bound_cache(self):
        name = "OPERA@20261019T1340@0@DBZH.tiff"
        params = dict(filename=name, source_time=self.when, now=self.now,
                      z=6, x=33, y=19, quality_version="unknown")
        first = policy.tile_cache_key(**params, palette_version="v1")
        self.assertEqual(first, ("DBZH", "20261019T134000Z", "6", "33", "19", "v1", "unknown"))
        self.assertNotEqual(first, policy.tile_cache_key(**params, palette_version="v2"))

if __name__ == "__main__":
    unittest.main()
