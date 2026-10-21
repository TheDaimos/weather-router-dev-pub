"""F7 real archived Alpine copyright/NOTICE/license artifact evidence tests."""
from __future__ import annotations
from io import BytesIO
import importlib.util
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import sys
_SCRIPTS=str(Path(__file__).resolve().parents[1]/"scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0,_SCRIPTS)

spec=importlib.util.spec_from_file_location(
    "f7_apk_docs",Path(__file__).resolve().parents[1]/"scripts/f7_apk_license_docs.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class OriginalLicenceDocs(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.folder=Path(self.tmp.name)
        self.name="gdal-libs"
        self.version="3.13.3-r0"
        self.path=self.folder/f"{self.name}-{self.version}.apk"
        self.pkginfo=b"pkgname = gdal-libs\npkgver = 3.13.3-r0\nlicense = MIT\norigin = gdal\n"
        self.copyright=b"Copyright holders. Redistribution terms subject to manual review."
        with tarfile.open(self.path,"w:gz") as tar:
            for name,raw in ((".PKGINFO",self.pkginfo),
                             ("usr/share/licenses/gdal-libs/COPYING",self.copyright)):
                info=tarfile.TarInfo(name)
                info.size=len(raw)
                tar.addfile(info,BytesIO(raw))
        self.report={
            "schema":"weather_router.f7.official_apk_archive_candidates.v1",
            "wheel_sha256":"b"*64,
            "packages":[{"name":self.name,"version":self.version,
                         "archive_sha256":hashlib.sha256(self.path.read_bytes()).hexdigest(),
                         "apk_verify_result":"VALID_AGAINST_CI_CONTAINER_KEYS"}]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_original_license_file_sha_and_pkginfo(self):
        evidence=mod.audit(self.report,self.folder)
        self.assertEqual(evidence["packages_with_original_license_docs"],1)
        row=evidence["packages"][0]
        self.assertEqual(row["pkginfo"]["license"],"MIT")
        self.assertEqual(row["license_documents"][0]["sha256"],
                         hashlib.sha256(self.copyright).hexdigest())
        self.assertFalse(evidence["original_copyright_and_distribution_obligations_reviewed"])
        self.assertEqual(evidence["ha_installation"],"BLOCKED")

    def test_invalid_signature_does_not_become_evidence(self):
        self.report["packages"][0]["apk_verify_result"]="SIGNATURE_FAILED"
        evidence=mod.audit(self.report,self.folder)
        self.assertEqual(evidence["document_hashes_count"],0)
        self.assertFalse(evidence["packages"][0]["license_cleared"])

    def test_mutated_apk_sha_is_rejected(self):
        self.path.write_bytes(self.path.read_bytes()+b"mutation")
        evidence=mod.audit(self.report,self.folder)
        self.assertEqual(evidence["document_hashes_count"],0)

if __name__=="__main__":
    unittest.main()
