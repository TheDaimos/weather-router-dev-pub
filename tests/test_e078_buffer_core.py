"""E-078 isolated, synthetic and public-safe regressions."""
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / "custom_components/weather_router/buffer_core.py"
spec = importlib.util.spec_from_file_location("wr_e078_buffer", MODULE)
buffer = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = buffer
spec.loader.exec_module(buffer)


class BufferTests(unittest.TestCase):
    def setUp(self):
        self.time = 100.0
        self.buf = buffer.IsolatedBuffer(max_entries=2, max_bytes=8,
                                         clock=lambda: self.time)
        self.allow = buffer.BufferPolicy(True, True, False, 10)

    def test_disabled_is_inert(self):
        self.assertFalse(self.buf.write("a", b"one", policy=self.allow, authorized=True))
        self.assertIsNone(self.buf.read("a", policy=self.allow, authorized=True))

    def test_enable_store_read_disable_erases(self):
        self.buf.set_enabled(True)
        self.assertTrue(self.buf.write("a", b"one", policy=self.allow, authorized=True))
        self.assertEqual(self.buf.read("a", policy=self.allow, authorized=True), b"one")
        self.buf.set_enabled(False)
        self.assertEqual(self.buf.stats()["bytes"], 0)
        self.buf.set_enabled(True)
        self.assertIsNone(self.buf.read("a", policy=self.allow, authorized=True))

    def test_expiry(self):
        self.buf.set_enabled(True)
        self.buf.write("a", b"one", policy=self.allow, authorized=True)
        self.time += 10
        self.assertIsNone(self.buf.read("a", policy=self.allow, authorized=True))

    def test_policy_and_authorization_recheck_on_serve(self):
        self.buf.set_enabled(True)
        self.buf.write("a", b"one", policy=self.allow, authorized=True)
        self.assertIsNone(self.buf.read("a", policy=self.allow, authorized=False))
        self.assertIsNone(self.buf.read("a", policy=buffer.BufferPolicy(), authorized=True))

    def test_tightened_retention_is_enforced_on_read(self):
        self.buf.set_enabled(True)
        self.assertTrue(self.buf.write("a", b"one",
                                       policy=self.allow, authorized=True))
        self.time += 5
        stricter = buffer.BufferPolicy(True, True, False, 3)
        self.assertIsNone(self.buf.read("a", policy=stricter, authorized=True))
        self.assertEqual(self.buf.stats()["bytes"], 0)

    def test_prefetch_denied_separately(self):
        self.buf.set_enabled(True)
        self.assertFalse(self.buf.write("a", b"one", policy=self.allow,
                                        authorized=True, prefetch=True))
        self.assertTrue(self.buf.write("a", b"one", policy=self.allow, authorized=True))

    def test_evict_bounded_bytes_and_entries(self):
        self.buf.set_enabled(True)
        for name in "abc":
            self.assertTrue(self.buf.write(name, b"1234",
                                           policy=self.allow, authorized=True))
        self.assertEqual(self.buf.stats()["entries"], 2)
        self.assertEqual(self.buf.stats()["bytes"], 8)
        self.assertIsNone(self.buf.read("a", policy=self.allow, authorized=True))

    def test_invalid_policy_fails_closed(self):
        self.buf.set_enabled(True)
        self.assertFalse(self.buf.write("a", b"1", policy=object(), authorized=True))
        with self.assertRaises(ValueError):
            buffer.validate_policy(buffer.BufferPolicy(ttl_seconds=3601))

    def test_not_exposing_runtime_token_or_private_metadata(self):
        self.assertEqual(set(self.buf.stats()), {"enabled", "entries", "bytes", "hits"})


if __name__ == "__main__":
    unittest.main()
