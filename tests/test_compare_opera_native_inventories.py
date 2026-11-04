"""Offline F7 musllinux inventory comparison. Synthetic fixtures only."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "f7_compare", Path(__file__).resolve().parents[1] /
    "scripts/compare_opera_native_inventories.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def fixture(hash_char="a", native_hash="3", extension_hash="2"):
    files = [
        {"path": "rasterio.libs/libgdal-12345678.so.39",
         "sha256": native_hash * 64, "size_bytes": 123, "elf_magic": True},
        {"path": "rasterio/_io.cpython-314-x86_64-linux-musl.so",
         "sha256": extension_hash * 64, "size_bytes": 567, "elf_magic": True},
        {"path": "rasterio-1.5.2.dist-info/RECORD",
         "sha256": "5" * 64, "size_bytes": 42, "elf_magic": False},
        {"path": "rasterio/proj_data/proj.db",
         "sha256": "6" * 64, "size_bytes": 12, "elf_magic": False},
    ]
    return {
        "schema": "weather_router.f7.native_candidate_inventory.v2",
        "status": "UNAPPROVED_NOT_DISTRIBUTABLE",
        "target_abi": "cp314-cp314-musllinux_1_2_x86_64",
        "candidate": {"sha256": hash_char * 64},
        "files": files, "files_count": len(files), "native_elf_count": 2}

class InventoryComparison(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.a = Path(self.folder.name) / "a.json"
        self.b = Path(self.folder.name) / "b.json"
        self.write()

    def tearDown(self):
        self.folder.cleanup()

    def write(self, first=None, second=None):
        self.a.write_text(json.dumps(fixture() if first is None else first))
        self.b.write_text(json.dumps(fixture("b") if second is None else second))

    def test_extension_drift_is_not_a_reproducibility_pass(self):
        self.write(second=fixture("b", extension_hash="7"))
        result = mod.compare(self.a, self.b)
        self.assertEqual(result["changed_member_count"], 1)
        self.assertEqual(result["changed_members"][0]["category"],
                         "rasterio_native_extensions")
        self.assertTrue(result["bundled_native_content_identical"])
        self.assertTrue(result["projection_and_gdal_resources_identical"])
        self.assertFalse(result["wheel_sha256_identical"])
        self.assertFalse(result["bitwise_reproducible_wheel_proven"])
        self.assertEqual(result["ha_installation"], "BLOCKED")

    def test_bundled_gdal_change_is_not_hidden(self):
        self.write(second=fixture("b", native_hash="8"))
        result = mod.compare(self.a, self.b)
        self.assertFalse(result["bundled_native_content_identical"])
        self.assertEqual(result["changed_members"][0]["category"],
                         "bundled_native_libraries")

    def test_equal_members_different_wheel_sha_is_still_not_reproducible(self):
        result = mod.compare(self.a, self.b)
        self.assertEqual(result["changed_member_count"], 0)
        self.assertFalse(result["wheel_sha256_identical"])
        self.assertFalse(result["bitwise_reproducible_wheel_proven"])

    def test_reject_forged_approval_and_broken_counts(self):
        for override in ({"status": "APPROVED"}, {"files_count": 100},
                         {"native_elf_count": 1},
                         {"target_abi": "cp314-manylinux"}):
            altered = fixture("b")
            altered.update(override)
            self.write(second=altered)
            with self.subTest(override=override), self.assertRaises(ValueError):
                mod.compare(self.a, self.b)

    def test_reject_symlink_and_duplicate_entries(self):
        link = Path(self.folder.name) / "symlink"
        link.symlink_to(self.a)
        with self.assertRaises(ValueError):
            mod.compare(link, self.b)
        altered = fixture("b")
        altered["files"].append(dict(altered["files"][0]))
        altered["files_count"] += 1
        self.write(second=altered)
        with self.assertRaises(ValueError):
            mod.compare(self.a, self.b)

if __name__ == "__main__":
    unittest.main()
