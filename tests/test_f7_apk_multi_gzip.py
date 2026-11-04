"""F7 Alpine v2 multistream signature/control/payload parser regressions."""
from __future__ import annotations

import gzip
from io import BytesIO
import importlib.util
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/"scripts"))

from f7_apk_multi_gzip import open_apk_tar_segments, UnsafeApkArchive

def module(name):
    s=importlib.util.spec_from_file_location(name,BASE/"scripts"/(name+".py"))
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    return m
cor=module("f7_correlate_apk_archives")
lic=module("f7_apk_license_docs")

def segment(names):
    b=BytesIO()
    with tarfile.open(fileobj=b,mode="w") as archive:
        for filename,raw in names:
            i=tarfile.TarInfo(filename)
            i.size=len(raw)
            archive.addfile(i,BytesIO(raw))
    return gzip.compress(b.getvalue())

class ThreePartApk(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.p=Path(self.tmp.name)/"test.apk"
        self.native=b"\x7fELF"+b"original-c-library"*3
        self.legal=b"SPDX-ID: BSD-3-Clause\nCopyright original upstream\n"
        self.p.write_bytes(
            segment([(".SIGN.RSA.test.pub",b"fake signature strictly test-only")])+
            segment([(".PKGINFO",b"pkgname = example\npkgver = 1.2-r0\nlicense = BSD-3-Clause\n")])+
            segment([("usr/lib/libexample.so.1",self.native),
                     ("usr/share/licenses/example/COPYING",self.legal)]))

    def tearDown(self):self.tmp.cleanup()

    def test_all_three_gzip_tars_read_without_extraction(self):
        parts=open_apk_tar_segments(self.p)
        self.assertEqual(len(parts),3)
        result=cor._candidates(self.p,{"libexample.so.1"})
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["bytes"],len(self.native))
        metadata,docs=lic.read_doc(self.p)
        self.assertEqual(metadata["pkgname"],"example")
        self.assertEqual(metadata["pkgver"],"1.2-r0")
        self.assertEqual(len(docs),1)
        self.assertEqual(docs[0]["bytes"],len(self.legal))

    def test_corrupt_second_member_fails_closed(self):
        self.p.write_bytes(self.p.read_bytes()[:-22])
        with self.assertRaises(UnsafeApkArchive):
            open_apk_tar_segments(self.p)

    def test_nongzip_and_trailing_bytes_rejected(self):
        self.p.write_bytes(b"ADB\x01untrusted-not-gzip")
        with self.assertRaises(UnsafeApkArchive):
            open_apk_tar_segments(self.p)
        self.p.write_bytes(segment([("hello",b"world")])+b"bad-trailing")
        with self.assertRaises(UnsafeApkArchive):
            open_apk_tar_segments(self.p)

if __name__=="__main__":
    unittest.main()
