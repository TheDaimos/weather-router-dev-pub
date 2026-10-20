"""F7 no-install candidate validation; standard-library-only isolated tests."""
import hashlib
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

    def test_runtime_remains_disabled(self):
        self.assertFalse(module.optional_runtime_status()["opera_native_enabled"])

if __name__ == "__main__":
    unittest.main()
