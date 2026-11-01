"""Neutral public v2 extension manifest and isolated registration test."""
import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest

pkg = types.ModuleType("wr_e078_extension_test")
pkg.__path__ = [str(Path(__file__).resolve().parents[1]
                      / "custom_components/weather_router")]
sys.modules[pkg.__name__] = pkg
core = importlib.import_module(pkg.__name__ + ".buffer_core")
policy = importlib.import_module(pkg.__name__ + ".buffer_policy")
loader = importlib.import_module(pkg.__name__ + ".buffer_policy_extension")


class ExtensionTests(unittest.TestCase):
    def test_standalone_manifest_loads_without_provider_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "sample_policy"
            directory.mkdir()
            (directory / "extension.json").write_text(
                '{"schema":"weather_router.extension.v2",'
                '"kind":"buffer_policy","id":"sample_policy"}', encoding="utf-8")
            (directory / "__init__.py").write_text(
                "from wr_e078_extension_test.buffer_core import BufferPolicy\n"
                "def buffer_policy(context):\n"
                "    return BufferPolicy(True, True, False, 8)\n", encoding="utf-8")
            registry = policy.BufferPolicyRegistry()
            extension_id = loader.load_policy_extension(directory, registry)
            self.assertEqual(extension_id, "sample_policy")
            context = policy.BufferContext("p", "c", "u", "region", "cache_write")
            self.assertTrue(registry.decide(context).allow_write)
            loader.unload_policy_extension(extension_id, registry)
            self.assertFalse(registry.decide(context).allow_write)

    def test_legacy_provider_manifest_is_not_misread_as_buffer_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "provider_extension"
            directory.mkdir()
            (directory / "extension.json").write_text(
                '{"schema":"weather_router.extension.v1",'
                '"kind":"provider","id":"provider_extension"}', encoding="utf-8")
            (directory / "__init__.py").write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                loader.validate_manifest(directory)

    def test_invalid_extra_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "sample_policy"
            directory.mkdir()
            (directory / "extension.json").write_text(
                '{"schema":"weather_router.extension.v2",'
                '"kind":"buffer_policy","id":"sample_policy","provider":"dummy"}',
                encoding="utf-8")
            (directory / "__init__.py").write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                loader.validate_manifest(directory)


if __name__ == "__main__":
    unittest.main()
