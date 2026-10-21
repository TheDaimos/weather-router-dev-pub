"""F7-L03 dynamic observation negative regressions."""
import importlib.util
import pathlib
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("f7_dynamic", ROOT / "scripts/f7_observe_elf_dynamic_transform.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class TestF7Dynamic(unittest.TestCase):
    def test_rejects_incomplete_evidence(self):
        with self.assertRaises(ValueError):
            module.inspect({"schema": "weather_router.f7.apk_embedded_binary_comparison.v1", "native_elf_count": 100}, "does-not-exist")

    def test_rejects_forged_wheel_digest(self):
        with self.assertRaises(ValueError):
            module.inspect({"schema": "weather_router.f7.apk_embedded_binary_comparison.v1",
                            "native_elf_count": 101, "elf_components": [{}]*101,
                            "wheel_sha256": "0"*64}, "does-not-exist")

    def test_rejects_invalid_elf(self):
        with self.assertRaises(ValueError):
            module.dynamics(b"unsafe input")

    def test_parses_real_compiled_elf_if_available(self):
        import shutil
        import subprocess
        executable = shutil.which("python3")
        if not executable or not shutil.which("readelf"):
            self.skipTest("readelf not available")
        data = pathlib.Path(executable).read_bytes()
        if not data.startswith(b"\x7fELF"):
            self.skipTest("platform is not ELF")
        observed = module.dynamics(data)
        self.assertIn(observed["readelf_status"], ("OBSERVED_NOT_ATTESTED", "UNAVAILABLE_OR_UNSUPPORTED"))

if __name__ == "__main__":
    unittest.main()
