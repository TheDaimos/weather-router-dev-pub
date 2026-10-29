"""F7 fixed source-tree regression: only disposable files, never HA."""
from __future__ import annotations
import importlib.util
from io import BytesIO
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location("f7_repro_source", Path(__file__).resolve().parents[1]/"scripts/f7_prepare_fixed_source.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class FixedSourceTreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.work=self.root/"fixed"
        self.dest=self.work/"rasterio-1.5.2"
        self.source=self.root/"rasterio-1.5.2.tar.gz"
        self.patch_root=patch.object(mod,"FIXED_ROOT",self.work)
        self.patch_dest=patch.object(mod,"SOURCE_ROOT",self.dest)
        self.patch_root.start()
        self.patch_dest.start()

    def tearDown(self):
        self.patch_dest.stop()
        self.patch_root.stop()
        self.tmp.cleanup()

    def tar(self, *, evil=None):
        with tarfile.open(self.source,"w:gz") as archive:
            for name, content in [
                ("rasterio-1.5.2/pyproject.toml", b"[build-system]\nrequires=[]\n"),
                ("rasterio-1.5.2/README.md", b"first")]:
                info=tarfile.TarInfo(name)
                info.size=len(content)
                archive.addfile(info,BytesIO(content))
            if evil is not None:
                info=tarfile.TarInfo(evil)
                if evil.endswith("symlink"):
                    info.type=tarfile.SYMTYPE
                    info.linkname="/etc/passwd"
                else:
                    info.size=1
                archive.addfile(info,BytesIO(b"x") if info.isfile() else None)

    def test_same_path_two_extracts_and_no_approval(self):
        self.tar()
        a=mod.prepare(self.source,target=self.dest)
        self.assertEqual((self.dest/"README.md").read_bytes(),b"first")
        (self.dest/"README.md").write_bytes(b"changed")
        b=mod.prepare(self.source,target=self.dest)
        self.assertEqual((self.dest/"README.md").read_bytes(),b"first")
        self.assertEqual(a,b)
        self.assertEqual(a["status"],"CI_ONLY_NOT_DISTRIBUTABLE")
        self.assertFalse(a["source_sha_independently_attested"])
        self.assertEqual(a["ha_installation"],"BLOCKED")

    def test_traversal_and_symlink_archive_members_rejected(self):
        for evil in ("rasterio-1.5.2/../../escape","rasterio-1.5.2/symlink"):
            with self.subTest(evil=evil):
                self.tar(evil=evil)
                with self.assertRaises(ValueError):
                    mod.prepare(self.source,target=self.dest)

    def test_other_tree_and_input_symlink_rejected(self):
        self.tar()
        with self.assertRaises(ValueError):
            mod.prepare(self.source,target=self.root/"other")
        alias=self.root/"alias"
        alias.symlink_to(self.source)
        with self.assertRaises(ValueError):
            mod.prepare(alias,target=self.dest)

    def test_bad_archive_name_or_missing_metadata_rejected(self):
        self.tar()
        wrong=self.root/"different.tar.gz"
        wrong.write_bytes(self.source.read_bytes())
        with self.assertRaises(ValueError):
            mod.prepare(wrong,target=self.dest)
        self.source.write_bytes(b"corrupted")
        with self.assertRaises(tarfile.TarError):
            mod.prepare(self.source,target=self.dest)

if __name__=="__main__":
    unittest.main()
