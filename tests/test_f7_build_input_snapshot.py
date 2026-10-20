"""Offline F7 build provenance snapshot: synthetic, no native execution."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

PATH=Path(__file__).resolve().parents[1]/"scripts/f7_build_input_snapshot.py"
spec=importlib.util.spec_from_file_location("f7_build_inputs",PATH)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class SnapshotTests(unittest.TestCase):
    def test_snapshot_never_grants_distribution(self):
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp)/"installed"
            f.write_text("P:libgdal\nV:3.13.3-r0\nL:MIT\n\nP:proj\nV:9.8.1-r0\nL:MIT\n",encoding="utf-8")
            report=mod.snapshot(str(f),wheel_sha256="a"*64)
            self.assertEqual(report["apk_package_count"],2)
            self.assertEqual(report["binary_distribution"],"BLOCKED")
            self.assertFalse(report["second_build_binary_identical"])
            self.assertFalse(report["base_image_immutable"])
            with self.assertRaises(ValueError):
                mod.snapshot(str(f),wheel_sha256="a"*63)
            with self.assertRaises(ValueError):
                mod.snapshot(str(f),wheel_sha256="a"*64,image_digest="latest")
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp)/"installed"
            f.write_text("P:x\nV:1\n")
            alias=Path(temp)/"alias"
            alias.symlink_to(f)
            with self.assertRaises(ValueError):
                mod.snapshot(str(alias),wheel_sha256="a"*64)

if __name__=="__main__":
    unittest.main()
