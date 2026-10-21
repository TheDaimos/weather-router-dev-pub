"""CI sandbox-only native package shelf tests, synthetic inert ZIP fixtures.

Never import the native wheel, write Home Assistant paths, or grant activation.
"""
from __future__ import annotations
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
m=load("f7_channel","custom_components/weather_router/opera_native_channel.py")
wheel_gate=load("f7_wheel_gate","custom_components/weather_router/opera_native_package.py")

class NativeShelfTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{"GITHUB_ACTIONS":"true","WR_OPERA_ISOLATED_CI":"1"})
        self.env.start()
        self.tmp=tempfile.TemporaryDirectory(prefix="f7-ci-")
        self.root=Path(self.tmp.name)
        self.inside=Path(tempfile.mkdtemp(prefix="f7-fixtures-"))
        self.fixture_dirs=[]
        self.shelf=m.PassiveNativeShelf(self.root)

    def tearDown(self):
        import shutil
        self.env.stop()
        self.tmp.cleanup()
        shutil.rmtree(self.inside)

    def candidate(self, suffix):
        sub=self.inside/suffix
        sub.mkdir()
        p=sub/m.WHEEL
        with ZipFile(p,"w") as z:
            z.writestr("rasterio-1.5.2.dist-info/WHEEL",
                       "Wheel-Version: 1.0\nTag: cp314-cp314-musllinux_1_2_x86_64\n")
            z.writestr("rasterio.libs/libgdal-demo.so",b"synthetic gdal "+suffix.encode())
            z.writestr("rasterio.libs/libproj-demo.so",b"synthetic proj")
            z.writestr("rasterio/proj_data/proj.db",b"fixture")
            z.writestr("rasterio/gdal_data/gdalvrt.xsd",b"fixture")
        sha=hashlib.sha256(p.read_bytes()).hexdigest()
        d={"schema":"weather_router.f7.native_package.v1",
           "package":m.WHEEL,"abi":"cp314-cp314-musllinux_1_2_x86_64",
           "sha256":sha,"rasterio":"1.5.2","gdal":"3.13.3","proj":"9.8.1"}
        prov={"schema":"weather_router.f7.provenance_envelope.v1",
              "status":"BOUND_UNAPPROVED_EVIDENCE_ONLY",
              "candidate":{"sha256":sha},
              "signature_envelope":{"independent_signature_verified":False},
              "ha_installation":"BLOCKED"}
        return p,d,prov

    def test_atomic_two_staged_candidates_rollback_without_activation(self):
        a=self.candidate("one")
        b=self.candidate("two")
        first=self.shelf.stage(*a,wheel_gate.inspect_candidate)
        self.assertEqual(first["staged_candidate"],a[1]["sha256"])
        later=self.shelf.stage(*b,wheel_gate.inspect_candidate)
        self.assertEqual(later["previous_candidate"],a[1]["sha256"])
        self.assertFalse(later["active"])
        again=m.PassiveNativeShelf(self.root)
        rolled=again.rollback()
        self.assertEqual(rolled["staged_candidate"],a[1]["sha256"])
        self.assertEqual(rolled["ha_installation"],"BLOCKED")
        self.assertEqual(rolled["runtime_native_import"],"FORBIDDEN")

    def test_interrupted_update_preserves_old_pointer_and_no_temp_files(self):
        a=self.candidate("one")
        b=self.candidate("two")
        self.shelf.stage(*a,wheel_gate.inspect_candidate)
        with self.assertRaisesRegex(m.ChannelBlocked,"simulated_interrupted_update"):
            self.shelf.stage(*b,wheel_gate.inspect_candidate,fail_before_commit=True)
        self.assertEqual(m.PassiveNativeShelf(self.root).status()["staged_candidate"],a[1]["sha256"])
        self.assertEqual(list(self.root.rglob(".wheel-*")),[])

    def test_digest_mismatch_or_unsigned_claim_never_activates(self):
        p,d,pr=self.candidate("one")
        d["sha256"]="e"*64
        with self.assertRaises(wheel_gate.NativePackageRejected):
            self.shelf.stage(p,d,pr,wheel_gate.inspect_candidate)
        self.assertIsNone(self.shelf.status()["staged_candidate"])
        p,d,pr=self.candidate("two")
        pr["signature_envelope"]["independent_signature_verified"]=True
        with self.assertRaises(m.ChannelBlocked):
            self.shelf.stage(p,d,pr,wheel_gate.inspect_candidate)

    def test_revoke_and_corrupt_state_fail_closed(self):
        item=self.candidate("one")
        self.shelf.stage(*item,wheel_gate.inspect_candidate)
        self.assertIsNone(self.shelf.revoke()["staged_candidate"])
        state=self.root/"state.json"
        state.write_text('{"schema":"weather_router.f7.offline_shelf.v1","active":"unsafe"}')
        with self.assertRaises(m.ChannelBlocked):
            m.PassiveNativeShelf(self.root)

    def test_outside_ci_and_symlink_root_rejected(self):
        with patch.dict(os.environ,{"GITHUB_ACTIONS":"false"}):
            with self.assertRaises(m.ChannelBlocked):
                m.PassiveNativeShelf(self.root)
        elsewhere=self.inside/"f7-ci-evil"
        with self.assertRaises(m.ChannelBlocked):
            m.PassiveNativeShelf(elsewhere)
        alias=Path(tempfile.gettempdir())/"f7-ci-alias"
        if alias.exists() or alias.is_symlink():
            self.skipTest("alias fixture exists")
        try:
            alias.symlink_to(self.root)
            with self.assertRaises(m.ChannelBlocked):
                m.PassiveNativeShelf(alias)
        finally:
            alias.unlink(missing_ok=True)

    def test_zip_path_traversal_and_missing_gdal_rejected(self):
        p,d,pr=self.candidate("one")
        with ZipFile(p,"a") as zip:
            zip.writestr("../escape",b"bad")
        d["sha256"]=hashlib.sha256(p.read_bytes()).hexdigest()
        pr["candidate"]["sha256"]=d["sha256"]
        with self.assertRaises(wheel_gate.NativePackageRejected):
            self.shelf.stage(p,d,pr,wheel_gate.inspect_candidate)
        self.assertFalse(self.shelf.status()["active"])

if __name__=="__main__":
    unittest.main()
