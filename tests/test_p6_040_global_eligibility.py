"""P6-040: global eligibility cannot be overridden by a consumer profile.

The production _candidate_enabled function is AST-extracted to avoid loading HA.
"""
import ast
from pathlib import Path
import types
import unittest
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "custom_components/weather_router/consumer_api.py"
PROFILES = ROOT / "custom_components/weather_router/consumer_profiles.py"

def load_function(path, name):
    source = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(x for x in source.body if isinstance(x, ast.FunctionDef) and x.name == name)
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    namespace = {"Any": Any, "Mapping": Mapping}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]

candidate_enabled = load_function(API, "_candidate_enabled")
profile_allows_provider = load_function(PROFILES, "profile_allows_provider")

class P6040GlobalGate(unittest.TestCase):
    def setUp(self):
        self.provider = types.SimpleNamespace(id="synthetic_provider", router_domains=("weather",))
        self.public_id = "weather.synthetic.test"
        self.state = dict(router_enabled=True, enabled_domains={"weather"}, enabled_providers={"synthetic_provider"})

    def test_router_off_is_hard_deny(self):
        self.state["router_enabled"] = False
        self.assertEqual(candidate_enabled(self.state, self.provider, self.public_id), (False, "router_disabled"))
        self.assertTrue(profile_allows_provider({}, self.provider.id))

    def test_domain_off_is_hard_deny(self):
        self.state["enabled_domains"] = set()
        self.assertEqual(candidate_enabled(self.state, self.provider, self.public_id), (False, "domain_disabled"))

    def test_provider_off_is_hard_deny(self):
        self.state["enabled_providers"] = set()
        self.assertEqual(candidate_enabled(self.state, self.provider, self.public_id), (False, "provider_disabled"))

    def test_provider_cannot_cross_declared_domains(self):
        self.provider.router_domains = ("space",)
        self.assertEqual(candidate_enabled(self.state, self.provider, self.public_id), (False, "domain_disabled"))

    def test_profile_adds_deny_but_never_grants(self):
        self.assertEqual(candidate_enabled(self.state, self.provider, self.public_id), (True, None))
        self.assertFalse(profile_allows_provider({"excluded_providers": [self.provider.id]}, self.provider.id))

if __name__ == "__main__":
    unittest.main()
