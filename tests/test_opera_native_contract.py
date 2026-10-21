"""F7 passive native contract regression. No HA, native imports, or installs."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location("f7_passive",Path(__file__).resolve().parents[1]/"custom_components/weather_router/opera_native_contract.py")
m=importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name]=m
spec.loader.exec_module(m)

class PassiveContract(unittest.TestCase):
    def descriptor(self):
        return {"schema":"weather_router.f7.native_package.v1","package":m.PACKAGE,
                "abi":m.ABI,"sha256":"a"*64,"rasterio":"1.5.2",
                "gdal":"3.13.3","proj":"9.8.1"}
    def runtime(self):
        return {"implementation":"CPython","python_tag":"cp314","libc":"musl","architecture":"x86_64"}
    def approvals(self):
        return {k:{"verified":True,"artifact_sha256":"a"*64,"evidence_ref":"independent-record"}
                for k in m.REQUIRED_EVIDENCE}
    def test_even_full_approval_does_not_enable_native_import(self):
        result=m.inspect_descriptor(self.descriptor(),self.approvals(),runtime=self.runtime())
        self.assertEqual(result.status,"BLOCKED")
        self.assertFalse(result.may_install)
        self.assertFalse(result.may_import)
        self.assertFalse(result.active)
        self.assertEqual(result.reason,"ha_install_and_opera_activation_not_authorized")
        self.assertLessEqual(result.diagnostic()["max_workers"],2)
    def test_missing_every_independent_attestation_fails(self):
        for key in m.REQUIRED_EVIDENCE:
            approvals=self.approvals()
            del approvals[key]
            with self.subTest(key=key):
                self.assertEqual(m.inspect_descriptor(self.descriptor(),approvals,runtime=self.runtime()).reason,
                                 "evidence_missing_"+key)
    def test_candidate_authority_not_enough(self):
        self.assertEqual(m.inspect_descriptor(self.descriptor(),None,runtime=self.runtime()).reason,
                         "independent_approvals_missing")
        self.assertFalse(m.inspect_descriptor({},self.approvals(),runtime=self.runtime()).may_import)
    def test_abi_and_hash_mismatch_rejected(self):
        for key,bad in (("abi","cp314-manylinux"),("gdal","0.0"),("sha256","bad"),
                        ("package","arbitrary.whl"),("proj","old")):
            d=self.descriptor()
            d[key]=bad
            with self.subTest(key=key):
                self.assertFalse(m.inspect_descriptor(d,self.approvals(),runtime=self.runtime()).active)
        for key,bad in (("python_tag","cp313"),("libc","glibc"),("architecture","aarch64")):
            runtime=self.runtime()
            runtime[key]=bad
            with self.subTest(key=key):
                self.assertEqual(m.inspect_descriptor(self.descriptor(),self.approvals(),runtime=runtime).reason,
                                 "runtime_abi_unverified")
    def test_rollback_never_imports_or_installs(self):
        result=m.rollback_contract(selected="new",previous="old")
        self.assertEqual(result["status"],"NOT_EXECUTED")
        self.assertEqual(result["native_import"],"FORBIDDEN")
        self.assertEqual(result["ha_installation"],"BLOCKED")
        self.assertIn("v1_v2",result["fallback"])

if __name__=="__main__":
    unittest.main()
