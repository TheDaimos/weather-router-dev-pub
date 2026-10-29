"""Behavioral tests of the real public OPERA atomic runtime (no HA activation)."""
from __future__ import annotations
import hashlib
import importlib.util
import sys
import tempfile
import threading
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components/weather_router"
PKG = "_wr_public_opera_runtime"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT)]
sys.modules[PKG] = pkg

def load(name):
    full = PKG + "." + name
    if full not in sys.modules:
        spec = importlib.util.spec_from_file_location(full, ROOT / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[full] = module
        spec.loader.exec_module(module)
    return sys.modules[full]

# Runtime depends on the public TileRegistration type, not on HA internals.
load("opera_frame_cache")
tile = types.ModuleType(PKG + ".opera_tile_http")
from dataclasses import dataclass
@dataclass(frozen=True)
class TileRegistration:
    frame: object
    unit: str
    palette: object
    palette_verified: bool
    attribution: str
    quality_verified: bool = False
    raster_metadata_verified: bool = False
tile.TileRegistration = TileRegistration
sys.modules[tile.__name__] = tile
runtime_module = load("opera_runtime")


class AtomicRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = runtime_module.OperaRuntime()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    def candidate(self, name, product="RATE", offset=0):
        data = name.encode()
        path = Path(self.tmp.name) / (name + ".tiff")
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        return self.runtime.prepare(
            source_path=path, product=product,
            valid_at=self.now + timedelta(seconds=offset),
            digest=digest, palette=lambda _: (0, 0, 0, 0),
            attribution="public synthetic", quality_verified=False,
            raster_metadata_verified=False, palette_verified=False)

    def test_dormant_provider_and_services(self):
        c = self.candidate("one")
        self.runtime.promote(c)
        self.assertFalse(self.runtime.enabled)
        self.assertTrue(all(v is False for v in self.runtime.services.values()))
        self.assertIsNone(self.runtime.lookup("RATE", c.stamp))

    def test_stage_does_not_publish(self):
        c = self.candidate("one")
        self.assertIsNone(self.runtime.registry.lookup("RATE", c.stamp))
        self.runtime.promote(c)
        self.assertIs(self.runtime.registry.lookup("RATE", c.stamp), c.registration)

    def test_failed_promotion_preserves_previous(self):
        c = self.candidate("one")
        self.runtime.promote(c)
        with self.assertRaises(ValueError):
            self.runtime.prepare(source_path=Path(self.tmp.name) / "missing",
                                 product="RATE", valid_at=self.now,
                                 digest="0"*64, palette=None, attribution="public")
        self.assertIs(self.runtime.registry.active("RATE").registration, c.registration)

    def test_old_and_conflicting_generation_rejected(self):
        older = self.candidate("old", offset=-60)
        newer = self.candidate("new")
        self.runtime.promote(newer)
        with self.assertRaisesRegex(ValueError, "older_cycle"):
            self.runtime.promote(older)
        conflict = self.candidate("conflict")
        with self.assertRaisesRegex(ValueError, "conflicting_cycle"):
            self.runtime.promote(conflict)
        self.assertEqual(self.runtime.registry.active("RATE").digest, newer.digest)

    def test_product_isolation(self):
        rate = self.candidate("rate")
        dbzh = self.candidate("dbzh", product="DBZH")
        self.runtime.promote(rate)
        self.runtime.promote(dbzh)
        self.assertEqual(self.runtime.registry.active("RATE").digest, rate.digest)
        self.assertEqual(self.runtime.registry.active("DBZH").digest, dbzh.digest)
        with self.assertRaisesRegex(ValueError, "product_pipeline_unverified"):
            self.candidate("acrr", product="ACRR")

    def test_evicted_candidate_rejected(self):
        old = self.candidate("one")
        for n in range(4):
            self.candidate("next"+str(n))
        with self.assertRaisesRegex(Exception, "staged_frame_evicted"):
            self.runtime.promote(old)
        self.assertIsNone(self.runtime.registry.active("RATE"))

    def test_leased_generation_survives_eviction(self):
        old = self.candidate("one")
        self.runtime.promote(old)
        frame = old.registration.frame
        with self.runtime.cache.lease(product="RATE", valid_at=frame.valid_at,
                                       digest=frame.digest):
            for n in range(4):
                self.candidate("extra"+str(n))
            self.assertTrue(frame.path.exists())
        self.assertFalse(frame.path.exists())

    def test_close_during_lease_preserves_file_until_release(self):
        c = self.candidate("closing")
        frame = c.registration.frame
        lease = self.runtime.cache.lease(
            product=frame.product, valid_at=frame.valid_at, digest=frame.digest)
        lease.__enter__()
        folder = self.runtime.cache._folder
        try:
            self.runtime.close()
            self.assertTrue(frame.path.is_file())
            self.assertIsNone(self.runtime.cache.get(
                product=frame.product, valid_at=frame.valid_at, digest=frame.digest))
            with self.assertRaisesRegex(Exception, "cache_closing"):
                self.candidate("new_after_close")
        finally:
            lease.__exit__(None, None, None)
        self.assertFalse(folder.exists(), "deferred cache directory not removed")

    def test_parallel_promotion_never_rolls_back(self):
        old = self.candidate("old", offset=-100)
        new = self.candidate("new")
        barrier = threading.Barrier(2)
        successes = []
        def publish(c):
            barrier.wait()
            try:
                self.runtime.promote(c)
                successes.append(c)
            except ValueError:
                pass
        a = threading.Thread(target=publish, args=(old,))
        b = threading.Thread(target=publish, args=(new,))
        a.start(); b.start(); a.join(); b.join()
        self.assertEqual(self.runtime.registry.active("RATE").digest, new.digest)

    def test_utc_age_boundaries(self):
        policy = runtime_module.utc_status
        self.assertEqual(policy(self.now-timedelta(seconds=900),now=self.now), "CURRENT")
        self.assertEqual(policy(self.now-timedelta(seconds=1501),now=self.now), "UNAVAILABLE")
        self.assertEqual(policy(self.now-timedelta(seconds=1201),now=self.now,
                                stale_after_seconds=1200,serve_stale=True), "STALE")
        self.assertEqual(policy(self.now-timedelta(seconds=3601),now=self.now,
                                serve_stale=True), "UNAVAILABLE")
        self.assertEqual(policy(self.now+timedelta(seconds=1),now=self.now), "UNAVAILABLE")
        self.assertEqual(policy(self.now.replace(tzinfo=None),now=self.now), "UNAVAILABLE")

if __name__ == "__main__":
    unittest.main()
