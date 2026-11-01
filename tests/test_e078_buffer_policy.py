"""E-078 executable policy hook tests without Home Assistant and without network."""
import importlib
import sys
import types
from pathlib import Path
import unittest

root = Path(__file__).resolve().parents[1] / "custom_components/weather_router"
pkg = types.ModuleType("wr_e078_policy_test")
pkg.__path__ = [str(root)]
sys.modules[pkg.__name__] = pkg
core = importlib.import_module(pkg.__name__ + ".buffer_core")
policy = importlib.import_module(pkg.__name__ + ".buffer_policy")


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.clock = 0
        self.cache = core.IsolatedBuffer(clock=lambda: self.clock)
        self.cache.set_enabled(True)
        self.registry = policy.BufferPolicyRegistry()
        self.facade = policy.PolicyControlledBuffer(self.cache, self.registry)
        self.ctx = policy.BufferContext("provider", "rain", "consumer_a", "region@time", "cache_write")
        self.ok = lambda ctx: core.BufferPolicy(True, True, True, 90)

    def test_no_policy_never_caches(self):
        self.assertFalse(self.facade.write(self.ctx, b"x", provider_authorized=True))

    def test_real_hooks_for_write_prefetch_and_serve(self):
        seen = []
        def extension(ctx):
            seen.append(ctx.operation)
            return self.ok(ctx)
        self.registry.register("example", extension)
        self.assertTrue(self.facade.write(self.ctx, b"x", provider_authorized=True))
        self.assertEqual(self.facade.read(self.ctx, provider_authorized=True), b"x")
        self.assertTrue(self.facade.write(self.ctx, b"y", provider_authorized=True, prefetch=True))
        self.assertEqual(seen, ["cache_write", "cache_serve", "prefetch"])

    def test_unload_revokes_old_data(self):
        self.registry.register("example", self.ok)
        self.facade.write(self.ctx, b"x", provider_authorized=True)
        self.registry.unregister("example")
        self.registry.register("example", self.ok)
        self.assertIsNone(self.facade.read(self.ctx, provider_authorized=True))

    def test_no_provider_permission_escalation(self):
        self.registry.register("example", self.ok)
        self.assertFalse(self.facade.write(self.ctx, b"x", provider_authorized=False))
        self.assertIsNone(self.facade.read(self.ctx, provider_authorized=False))

    def test_consumer_and_spatial_context_isolated(self):
        self.registry.register("example", self.ok)
        self.facade.write(self.ctx, b"x", provider_authorized=True)
        b = policy.BufferContext("provider", "rain", "consumer_b", "region@time", "cache_serve")
        c = policy.BufferContext("provider", "rain", "consumer_a", "elsewhere", "cache_serve")
        self.assertIsNone(self.facade.read(b, provider_authorized=True))
        self.assertIsNone(self.facade.read(c, provider_authorized=True))

    def test_conflicting_rules_fail_closed(self):
        self.registry.register("example", self.ok)
        self.registry.register("other", self.ok)
        self.assertFalse(self.facade.write(self.ctx, b"x", provider_authorized=True))

    def test_exception_fail_closed(self):
        def broken(ctx):
            raise RuntimeError("synthetic failure")
        self.registry.register("example", broken)
        self.assertFalse(self.facade.write(self.ctx, b"x", provider_authorized=True))

    def test_prefetch_policy_respected(self):
        self.registry.register("example", lambda ctx: core.BufferPolicy(True, True, False, 90))
        self.assertFalse(self.facade.write(self.ctx, b"x", provider_authorized=True, prefetch=True))
        self.assertTrue(self.facade.write(self.ctx, b"x", provider_authorized=True))


if __name__ == "__main__":
    unittest.main()
