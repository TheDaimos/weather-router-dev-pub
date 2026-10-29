"""Tests for dormant immutable OPERA frame admission."""
import hashlib
import importlib.util
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import unittest

path = Path(__file__).resolve().parents[1] / "custom_components/weather_router/opera_frame_cache.py"
spec = importlib.util.spec_from_file_location("opera_frame_cache", path)
cache_module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = cache_module
spec.loader.exec_module(cache_module)

class FrameCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = datetime(2026, 10, 19, 13, 40, tzinfo=timezone.utc)
        self.cache = cache_module.ImmutableFrameCache(max_frames=2)
    def tearDown(self):
        self.cache.close()
        self.tmp.cleanup()
    def sample(self, text):
        file = Path(self.tmp.name) / (text + ".tiff")
        file.write_bytes(text.encode())
        return file, hashlib.sha256(text.encode()).hexdigest()
    def test_verified_immutable_copy_reused(self):
        source, digest = self.sample("one")
        original = self.cache.admit(source_path=source, product="DBZH",
                                    valid_at=self.t, expected_sha256=digest)
        source.write_bytes(b"changed")
        same = self.cache.admit(source_path=source, product="DBZH",
                                valid_at=self.t, expected_sha256=digest)
        self.assertIs(original, same)
        self.assertEqual(original.path.read_bytes(), b"one")
        self.assertEqual(self.cache.hash_operations, 1)
    def test_fail_closed_wrong_hash(self):
        source, digest = self.sample("one")
        with self.assertRaises(cache_module.FrameCacheError):
            self.cache.admit(source_path=source, product="RATE", valid_at=self.t,
                             expected_sha256="0" * 64)
        self.assertIsNone(self.cache.get(product="RATE", valid_at=self.t, digest=digest))
    def test_evict_and_separate_revisions(self):
        for value in ("one", "two", "three"):
            source, digest = self.sample(value)
            self.cache.admit(source_path=source, product="DBZH", valid_at=self.t,
                             expected_sha256=digest)
        first_digest = hashlib.sha256(b"one").hexdigest()
        self.assertIsNone(self.cache.get(product="DBZH", valid_at=self.t, digest=first_digest))
        self.assertEqual(self.cache.hash_operations, 3)
    def test_lease_survives_eviction_until_reader_finishes(self):
        source, digest = self.sample("one")
        frame = self.cache.admit(source_path=source, product="RATE",
                                 valid_at=self.t, expected_sha256=digest)
        with self.cache.lease(product="RATE", valid_at=self.t, digest=digest) as pinned:
            self.assertEqual(frame.path, pinned.path)
            for value in ("two", "three"):
                other, other_digest = self.sample(value)
                self.cache.admit(source_path=other, product="RATE",
                                 valid_at=self.t, expected_sha256=other_digest)
            self.assertIsNone(self.cache.get(product="RATE", valid_at=self.t, digest=digest))
            self.assertEqual(frame.path.read_bytes(), b"one")
            with self.assertRaisesRegex(cache_module.FrameCacheError, "active_readers"):
                self.cache.close()
        self.assertFalse(frame.path.exists())

    def test_lease_missing_frame_fails_closed(self):
        with self.assertRaisesRegex(cache_module.FrameCacheError, "frame_unavailable"):
            with self.cache.lease(product="RATE", valid_at=self.t, digest="0" * 64):
                self.fail("missing frame leased")

    def test_reject_time_and_limits(self):
        source, digest = self.sample("one")
        with self.assertRaises(cache_module.FrameCacheError):
            self.cache.admit(source_path=source, product="RATE",
                             valid_at=self.t.replace(tzinfo=None), expected_sha256=digest)
        with self.assertRaises(cache_module.FrameCacheError):
            cache_module.ImmutableFrameCache(max_frames=0)

if __name__ == "__main__":
    unittest.main()
