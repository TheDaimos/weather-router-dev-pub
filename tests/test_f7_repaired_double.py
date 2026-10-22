"""Regression checks for read-only F7 repaired-wheel comparator."""
import importlib.util
import io
import pathlib
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("f7_repaired", ROOT / "scripts/probe_f7_repaired_double.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

class RepairedDoubleTests(unittest.TestCase):
    def wheel(self, directory, archive_name="test.whl", body=b"same", timestamp=(2024, 1, 1, 0, 0, 0)):
        path = pathlib.Path(directory) / archive_name
        with zipfile.ZipFile(path, "w") as dest:
            info = zipfile.ZipInfo("rasterio/example.txt", date_time=timestamp)
            dest.writestr(info, body)
        return path

    def test_identical_archives_still_unapproved(self):
        with tempfile.TemporaryDirectory() as t:
            a = pathlib.Path(t) / "a"
            b = pathlib.Path(t) / "b"
            a.mkdir()
            b.mkdir()
            result = module.compare(self.wheel(a), self.wheel(b))
            self.assertEqual(result["status"], "BIT_IDENTICAL_UNAPPROVED")
            self.assertEqual(result["different_member_count"], 0)
            self.assertEqual(result["ha_installation"], "BLOCKED")
            self.assertFalse(result["licenses_cleared"])

    def test_changed_contents_and_metadata(self):
        with tempfile.TemporaryDirectory() as t:
            a, b = pathlib.Path(t) / "a", pathlib.Path(t) / "b"
            a.mkdir()
            b.mkdir()
            result = module.compare(self.wheel(a), self.wheel(b, body=b"different"))
            self.assertEqual(result["status"], "DIFFERENT_UNAPPROVED")
            self.assertEqual(result["different_member_names"], ["rasterio/example.txt"])
            result = module.compare(self.wheel(a), self.wheel(b, timestamp=(2024, 2, 1, 0, 0, 0)))
            self.assertEqual(result["different_member_count"], 1)

    def test_rejects_same_path_and_product_mismatch(self):
        with tempfile.TemporaryDirectory() as t:
            path = self.wheel(t)
            with self.assertRaises(ValueError):
                module.compare(path, path)
            other = pathlib.Path(t) / "other"
            other.mkdir()
            with self.assertRaises(ValueError):
                module.compare(path, self.wheel(other, archive_name="another.whl"))

    def test_rejects_traversal_and_duplicate_members(self):
        with tempfile.TemporaryDirectory() as t:
            a, b = pathlib.Path(t) / "a", pathlib.Path(t) / "b"
            a.mkdir()
            b.mkdir()
            left = self.wheel(a)
            right = b / "test.whl"
            with zipfile.ZipFile(right, "w") as archive:
                archive.writestr("../escape", b"evil")
            with self.assertRaises(ValueError):
                module.compare(left, right)
            with zipfile.ZipFile(right, "w") as archive:
                archive.writestr("same", b"x")
                archive.writestr("same", b"y")
            with self.assertRaises(ValueError):
                module.compare(left, right)

if __name__ == "__main__":
    unittest.main()
