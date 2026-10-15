"""E-078 staged HA switch contract, without HA imports or provider access.

This is static containment verification, not an HA runtime acceptance test.
"""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components/weather_router"


class PreparationSwitchContractTests(unittest.TestCase):
    def test_core_defaults_to_disabled(self):
        source = (INTEGRATION / "const.py").read_text(encoding="utf-8")
        self.assertIn('CONF_BUFFER_ENABLED: Final = "buffer_enabled"', source)
        self.assertIn("CONF_BUFFER_ENABLED: False", source)
        self.assertIn("Platform.SWITCH", source)

    def test_isolated_runtime_is_disabled_on_unload(self):
        source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("buffer_runtime.set_enabled(False)", source)
        self.assertIn("buffer_runtime.set_enabled(options[CONF_BUFFER_ENABLED])", source)

    def test_switch_exposes_only_preparation(self):
        source = (INTEGRATION / "switch.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("data_path_connected", source)
        self.assertIn("False", source)
        self.assertIn("CONF_BUFFER_ENABLED", source)

    def test_lab_has_real_switch_service_action(self):
        source = (INTEGRATION / "frontend/weather-router-lab.js").read_text(encoding="utf-8")
        self.assertIn('id="e078-buffer-button"', source)
        self.assertIn('callService("switch",', source)
        self.assertIn("BUFFER_PREP_ENTITY", source)

    def test_legacy_provider_manifest_dataclass_preserved(self):
        source = (INTEGRATION / "extensions.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        spec = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "ExtensionSpec")
        self.assertEqual(len(spec.decorator_list), 1)
        decorator = spec.decorator_list[0]
        self.assertIsInstance(decorator, ast.Call)
        self.assertEqual(getattr(decorator.func, "id", None), "dataclass")
        self.assertIn("_DedicatedBufferPolicyManifest", source)

    def test_no_implicit_consumer_data_path_activation(self):
        for filename in ("consumer_api.py", "consumer_raster_mosaic_api.py"):
            path = INTEGRATION / filename
            if path.is_file():
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("buffer_runtime", source)
                self.assertNotIn("buffer_policy_extension", source)


if __name__ == "__main__":
    unittest.main()
