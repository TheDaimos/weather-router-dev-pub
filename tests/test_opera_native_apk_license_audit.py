"""F7 fail-closed native Alpine APK ownership/licence attribution tests."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "audit_f7_licenses", ROOT / "scripts/audit_opera_native_apk_licenses.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ApkSourceAttribution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inventory = self.root / "inventory.json"
        self.db = self.root / "installed"
        self.write_inventory()
        self.db.write_text(
            "P:gdal-libs\nV:3.13.3-r0\nL:MIT\no:gdal\n"
            "F:usr/lib\nR:libgdal.so.39.3.13.3\n\n"
            "P:libz\nV:1.3.2-r0\nL:Zlib\no:zlib\n"
            "F:lib\nR:libz.so.1\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def write_inventory(self, **changes):
        source = dict(
            schema="weather_router.f7.native_candidate_inventory.v2",
            status="UNAPPROVED_NOT_DISTRIBUTABLE",
            target_abi="cp314-cp314-musllinux_1_2_x86_64",
            files=[
                {"path": "rasterio.libs/libgdal-e11df065.so.39.3.13.3",
                 "sha256": "a" * 64, "elf_magic": True},
                {"path": "rasterio/_io.cpython-314-x86_64-linux-musl.so",
                 "sha256": "b" * 64, "elf_magic": True},
                {"path": "rasterio.libs/libother-01234567.so.1",
                 "sha256": "c" * 64, "elf_magic": True},
                {"path": "rasterio/LICENSE.txt", "sha256": "d" * 64,
                 "elf_magic": False}],
            files_count=4, native_elf_count=3,
            python_distribution_metadata={"license_expression": "BSD-3-Clause"},
            candidate={"sha256": "f" * 64})
        source.update(changes)
        self.inventory.write_text(json.dumps(source), encoding="utf-8")

    def test_real_renamed_soname_candidate_without_faking_license_pass(self):
        result = mod.audit(self.inventory, self.db)
        self.assertEqual(result["native_elf_count"], 3)
        self.assertEqual(result["apk_filename_candidate_count"], 1)
        self.assertEqual(result["unresolved_component_count"], 1)
        self.assertEqual(result["apk_installed_package_count"], 2)
        row = result["elf_candidates"][0]
        self.assertEqual(row["apk_source_candidates"][0]["package"], "gdal-libs")
        self.assertEqual(row["apk_source_candidates"][0]["version"], "3.13.3-r0")
        self.assertEqual(row["attribution_confidence"], "filename_only_not_binary_proof")
        self.assertEqual(result["elf_candidates"][1]["attribution_confidence"],
                         "wheel_metadata_not_transitive_binary_license")
        self.assertEqual(result["elf_candidates"][2]["attribution_confidence"], "unresolved")
        self.assertFalse(result["mapping_is_binary_hash_verified"])
        self.assertFalse(result["declared_apk_licenses_individually_verified"])
        self.assertFalse(result["full_sbom_approved"])
        self.assertEqual(result["ha_installation"], "BLOCKED")
        self.assertEqual(result["status"], "UNAPPROVED_NOT_DISTRIBUTABLE")

    def test_truncated_or_untrustworthy_inventory_rejected(self):
        for altered in (
            {"files_count": 2},
            {"native_elf_count": 2},
            {"target_abi": "cp314-manylinux_x86_64"},
            {"status": "APPROVED"},
        ):
            with self.subTest(altered=altered):
                self.write_inventory(**altered)
                with self.assertRaises(ValueError):
                    mod.audit(self.inventory, self.db)

    def test_ambiguous_file_claims_are_not_silently_resolved(self):
        self.db.write_text(
            "P:gdal-a\nV:1-r0\nL:GPL-2.0-only\n"
            "F:usr/lib\nR:libgdal.so.39.3.13.3\n\n"
            "P:gdal-b\nV:2-r0\nL:MIT\n"
            "F:usr/lib\nR:libgdal.so.39.3.13.3\n",
            encoding="utf-8")
        result = mod.audit(self.inventory, self.db)
        self.assertEqual(len(result["elf_candidates"][0]["apk_source_candidates"]), 2)
        self.assertEqual(result["status"], "UNAPPROVED_NOT_DISTRIBUTABLE")

    def test_symlink_inputs_rejected(self):
        candidate = self.root / "link.json"
        candidate.symlink_to(self.inventory)
        with self.assertRaises(ValueError):
            mod.audit(candidate, self.db)


if __name__ == "__main__":
    unittest.main()
