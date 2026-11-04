"""F7 actual APK/installed/repair SHA-chain regressions – synthetic inert bytes."""
from __future__ import annotations
import hashlib
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import sys
_SCRIPTS=str(Path(__file__).resolve().parents[1]/"scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0,_SCRIPTS)
from zipfile import ZipFile

BASE=Path(__file__).resolve().parents[1]
def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,BASE/"scripts"/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
probe=load("f7_actual_elf","f7_compare_installed_elf.py")
corr=load("f7_apk_correlate","f7_correlate_apk_archives.py")
fetch=load("f7_official_apks","f7_fetch_official_apks.py")

class OriginalBinaryChain(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/"usr/lib").mkdir(parents=True)
        self.native=b"\x7fELF"+b"unaltered-original" * 3
        (self.root/"usr/lib/libgdal.so.39").write_bytes(self.native)
        self.installed=self.root/"installed"
        self.installed.write_text("P:gdal-libs\nV:3.13.3-r0\nL:MIT\n"
                                  "o:gdal\nF:usr/lib\nR:libgdal.so.39\n")
        self.wheel=self.root/"candidate.whl"
        self.paths=["rasterio.libs/libgdal-12345678.so.39"]+[
            f"rasterio/module{i}.cpython-314-x86_64-linux-musl.so" for i in range(100)]
        self.bytes={p:(self.native if i==0 else b"\x7fELF"+str(i).encode())
                    for i,p in enumerate(self.paths)}
        with ZipFile(self.wheel,"w") as z:
            for p,raw in self.bytes.items():
                z.writestr(p,raw)
        wheelsha=hashlib.sha256(self.wheel.read_bytes()).hexdigest()
        self.inv={"schema":"weather_router.f7.native_candidate_inventory.v2",
                  "status":"UNAPPROVED_NOT_DISTRIBUTABLE",
                  "candidate":{"sha256":wheelsha},"native_elf_count":101,
                  "files_count":101,"files":[{"path":p,"sha256":hashlib.sha256(raw).hexdigest(),
                                              "elf_magic":True} for p,raw in self.bytes.items()]}
        self.audit={"schema":"weather_router.f7.native_apk_license_candidates.v1",
                    "status":"UNAPPROVED_NOT_DISTRIBUTABLE","wheel_sha256":wheelsha,
                    "elf_candidates":[{"wheel_path":p,"wheel_sha256":hashlib.sha256(raw).hexdigest(),
                        "attribution_confidence":("filename_only_not_binary_proof" if i==0
                                                  else "wheel_metadata_not_transitive_binary_license"),
                        "apk_source_candidates":([{"package":"gdal-libs","version":"3.13.3-r0",
                                                  "origin":"gdal","declared_license":"MIT"}] if i==0 else [])}
                        for i,(p,raw) in enumerate(self.bytes.items())]}
        self.apk_dir=self.root/"apks"
        self.apk_dir.mkdir()
        self.archive=self.apk_dir/"gdal-libs-3.13.3-r0.apk"
        with tarfile.open(self.archive,"w:gz") as tar:
            entry=tarfile.TarInfo("usr/lib/libgdal.so.39")
            entry.size=len(self.native)
            tar.addfile(entry,BytesIO(self.native))
        self.report={"schema":"weather_router.f7.official_apk_archive_candidates.v1",
                     "wheel_sha256":wheelsha,
                     "packages":[{"name":"gdal-libs","version":"3.13.3-r0",
                        "apk_verify_result":"VALID_AGAINST_CI_CONTAINER_KEYS",
                        "archive_sha256":hashlib.sha256(self.archive.read_bytes()).hexdigest()}]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_actual_original_byte_hash_and_101_rows(self):
        report=probe.compare(self.inv,self.audit,self.installed,self.wheel,
                             source_root=self.root,archive_dir=self.apk_dir)
        self.assertEqual(report["native_elf_count"],101)
        self.assertEqual(report["installed_elf_byte_identical_count"],1)
        row=report["elf_components"][0]
        self.assertEqual(row["origin_class"],"INSTALLED_ELF_BYTE_IDENTICAL_APK_UNATTESTED")
        self.assertEqual(row["original_resolved_path"],"usr/lib/libgdal.so.39")
        self.assertFalse(report["alpine_installed_database_signed"])
        self.assertEqual(report["ha_installation"],"BLOCKED")

    def test_signed_apk_bytes_match_but_external_root_still_unproven(self):
        binary=probe.compare(self.inv,self.audit,self.installed,self.wheel,
                             source_root=self.root,archive_dir=self.apk_dir)
        result=corr.correlate(binary,self.report,self.apk_dir)
        self.assertEqual(result["archive_elf_matches_installed_count"],1)
        self.assertEqual(result["archive_elf_matches_repaired_wheel_count"],1)
        self.assertFalse(result["independent_root_of_trust"])
        self.assertEqual(result["elf_components"][0]["status"],
                         "SIGNED_APK_MEMBER_EQUALS_WHEEL_ELF_KEY_NOT_INDEPENDENT")

    def test_modified_download_archive_hash_rejected(self):
        binary=probe.compare(self.inv,self.audit,self.installed,self.wheel,
                             source_root=self.root,archive_dir=self.apk_dir)
        self.archive.write_bytes(self.archive.read_bytes()+b"tamper")
        with self.assertRaises(ValueError):
            corr.correlate(binary,self.report,self.apk_dir)

    def test_unverified_signature_is_not_upgraded(self):
        binary=probe.compare(self.inv,self.audit,self.installed,self.wheel,
                             source_root=self.root,archive_dir=self.apk_dir)
        self.report["packages"][0]["apk_verify_result"]="SIGNATURE_FAILED"
        result=corr.correlate(binary,self.report,self.apk_dir)
        self.assertEqual(result["archive_elf_matches_installed_count"],0)
        self.assertEqual(result["ha_installation"],"BLOCKED")

    def test_mismatching_repaired_wheel_bytes_rejected(self):
        self.inv["files"][0]["sha256"]="0"*64
        with self.assertRaises(ValueError):
            probe.compare(self.inv,self.audit,self.installed,self.wheel,source_root=self.root)

    def test_official_fetch_plan_exact_versions_and_unsafe_names(self):
        selection=fetch.selected(self.audit)
        self.assertEqual(selection,[("gdal-libs","3.13.3-r0")])
        self.audit["elf_candidates"][0]["apk_source_candidates"][0]["package"]="../bad"
        with self.assertRaises(ValueError):
            fetch.selected(self.audit)

if __name__=="__main__":
    unittest.main()
