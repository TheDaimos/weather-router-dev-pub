"""F7 no-install candidate validation; standard-library-only isolated tests."""
import hashlib
import contextlib
import io
import json
import importlib.util
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

TARGET = Path(__file__).resolve().parents[1] / "custom_components/weather_router/opera_native_package.py"
spec = importlib.util.spec_from_file_location("opera_native_package", TARGET)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class AdmissionTests(unittest.TestCase):
    def make_wheel(self, root, *, gdal=True, proj=True, data=True, tag=True):
        path = Path(root) / module.WHEEL_NAME
        with ZipFile(path, "w") as f:
            f.writestr("rasterio-1.5.2.dist-info/WHEEL", "Wheel-Version: 1.0\nTag: " +
                       ("cp314-cp314-musllinux_1_2_x86_64" if tag else "py3-none-any") + "\n")
            if gdal: f.writestr("rasterio.libs/libgdal-demo.so", b"a")
            if proj: f.writestr("rasterio.libs/libproj-demo.so", b"b")
            if data:
                f.writestr("rasterio/proj_data/proj.db", b"c")
                f.writestr("rasterio/gdal_data/gdalvrt.xsd", b"d")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_valid_candidate_still_not_installable(self):
        with tempfile.TemporaryDirectory() as d:
            p, h = self.make_wheel(d)
            result = module.inspect_candidate(p, h)
            self.assertEqual(result["status"], "candidate_inventory_pass_not_installable")

    def test_mismatch_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            for setting in ({"gdal": False}, {"proj": False}, {"data": False}, {"tag": False}):
                p, h = self.make_wheel(d, **setting)
                with self.assertRaises(module.NativePackageRejected):
                    module.inspect_candidate(p, h)
            p, h = self.make_wheel(d)
            with self.assertRaises(module.NativePackageRejected):
                module.inspect_candidate(p, "0" * 64)

    def test_offline_inventory_not_distributable(self):
        script = Path(__file__).resolve().parents[1] / "scripts/inventory_opera_native_wheel.py"
        spec = importlib.util.spec_from_file_location("native_inventory", script)
        inventory = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inventory)
        with tempfile.TemporaryDirectory() as d:
            p, h = self.make_wheel(d)
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(inventory.main(["inventory", str(p), h]), 0)
            report = json.loads(captured.getvalue())
            self.assertEqual(report["status"], "UNAPPROVED_NOT_DISTRIBUTABLE")
            self.assertFalse(report["source_provenance_verified"])
            self.assertTrue(any(item["native"] for item in report["files"]))
            self.assertEqual(report["candidate"]["sha256"], h)


    def test_elf_inventory_dependency_evidence_is_never_a_distribution_pass(self):
        """Synthetic ELF-like bytes validate aggregation, not real GDAL ABI."""
        from unittest.mock import patch
        script = Path(__file__).resolve().parents[1] / "scripts/inventory_opera_native_wheel.py"
        spec = importlib.util.spec_from_file_location("native_inventory_elf", script)
        inv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inv)
        with tempfile.TemporaryDirectory() as folder:
            wheel, _ = self.make_wheel(folder)
            with ZipFile(wheel, "a") as f:
                f.writestr("rasterio.libs/libelf-test.so", b"\\x7fELF" + bytes(12))
                f.writestr("rasterio-1.5.2.dist-info/METADATA",
                           "Name: rasterio\\nVersion: 1.5.2\\n"
                           "License-Expression: BSD-3-Clause\\n"
                           "Requires-Dist: numpy\\n")
                f.writestr("rasterio-1.5.2.dist-info/licenses/LICENSE.txt",
                           "SYNTHETIC TEST LICENSE ONLY")
            digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
            with patch.object(inv, "_elf_dependencies", return_value={
                "elf_audit": "readelf_dynamic_pass",
                "needed": ["libgdal-example.so", "libc.musl-x86_64.so.1"],
                "soname": "libelf-test.so", "rpath": ["$ORIGIN"],
            }):
                report = inv.inventory(wheel, digest, require_elf=False)
            self.assertEqual(report["native_elf_count"], 1)
            self.assertEqual(report["files_count"], 8)
            self.assertIn("libc.musl-x86_64.so.1",
                          report["elf_external_dependency_names"])
            self.assertEqual(report["python_distribution_metadata"]["name"],
                             "rasterio")
            self.assertEqual(report["python_distribution_metadata"]["version"],
                             "1.5.2")
            self.assertEqual(report["components_license_review"], "REQUIRED")
            self.assertFalse(report["source_provenance_verified"])
            self.assertFalse(report["elf_dependency_closure_verified"])
            self.assertFalse(report["spdx_or_cyclonedx_compliant_sbom"])
            self.assertEqual(report["ha_installation"], "BLOCKED")
            self.assertEqual(report["status"], "UNAPPROVED_NOT_DISTRIBUTABLE")

    def test_strict_elf_mode_rejects_fake_native_shared_object(self):
        """A ZIP file named .so is not proof of a real ELF shared library."""
        script = Path(__file__).resolve().parents[1] / "scripts/inventory_opera_native_wheel.py"
        spec = importlib.util.spec_from_file_location("native_inventory_invalid", script)
        inv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inv)
        with tempfile.TemporaryDirectory() as folder:
            wheel, digest = self.make_wheel(folder)
            with self.assertRaisesRegex(ValueError, "native_object_missing_elf_magic"):
                inv.inventory(wheel, digest, require_elf=True)

    def test_runtime_remains_disabled(self):
        self.assertFalse(module.optional_runtime_status()["opera_native_enabled"])

if __name__ == "__main__":
    unittest.main()
