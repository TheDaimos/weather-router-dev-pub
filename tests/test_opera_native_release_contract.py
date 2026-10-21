"""F7 P1-L02 passive contract regression tests; no native import."""
from __future__ import annotations
import importlib.util
import sys
import unittest
from pathlib import Path

PATH=Path(__file__).resolve().parents[1]/"custom_components/weather_router/opera_native_release_contract.py"
spec=importlib.util.spec_from_file_location("f7_passive_native_contract",PATH)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def descriptor():
    return {"schema":mod.CONTRACT, "wheel_name":mod.WHEEL,
            "wheel_sha256":"a"*64, "abi":mod.ABI, "python_soabi":mod.SOABI,
            "rasterio":"1.5.2","gdal":"3.13.3","proj":"9.8.1",
            "max_worker_count":2, "max_archive_mib":250,
            "max_uncompressed_mib":700,"release_id":"f7-20261020-rc-test"}

class PassiveContractTests(unittest.TestCase):
    def test_strict_pinned_digest_is_not_activation(self):
        state=mod.PassiveNativeRelease()
        before=sys.path.copy()
        result=state.inspect(descriptor(), actual_soabi=mod.SOABI, trusted_digest="a"*64)
        self.assertEqual(result["state"],"CANDIDATE_PASSIVE_ONLY")
        self.assertFalse(result["native_activation_possible"])
        self.assertFalse(result["source_provenance_attested"])
        self.assertFalse(result["licenses_cleared"])
        self.assertEqual(result["max_parallel_native_workers"],0)
        self.assertEqual(result["opera_provider"],"BLOCKED")
        self.assertEqual(sys.path,before)
        self.assertNotIn("rasterio",sys.modules)
        self.assertFalse(hasattr(state,"activate"))

    def test_missing_independent_digest_and_mismatch_rejected(self):
        for digest in (None,"b"*64,"none",""):
            with self.subTest(digest=digest):
                result=mod.PassiveNativeRelease().inspect(
                    descriptor(),actual_soabi=mod.SOABI,trusted_digest=digest)
                self.assertEqual(result["state"],"DENIED")
                self.assertIsNone(result["candidate_sha256"])

    def test_runtime_soabi_version_and_wheel_rejected(self):
        for key,value in (("abi","manylinux"),
                          ("python_soabi","cpython-313-x86_64-linux-musl"),
                          ("gdal","0.0.1"),("wheel_name","rasterio.whl")):
            candidate=descriptor()
            candidate[key]=value
            with self.subTest(key=key):
                result=mod.PassiveNativeRelease().inspect(
                    candidate,actual_soabi=mod.SOABI,trusted_digest="a"*64)
                self.assertEqual(result["state"],"DENIED")
        result=mod.PassiveNativeRelease().inspect(
            descriptor(),actual_soabi="cpython-315-x86_64-linux-musl",
            trusted_digest="a"*64)
        self.assertEqual(result["reason"],"ha_python_abi_incompatible")

    def test_resource_caps_and_invalid_number_types(self):
        for key,value in (("max_worker_count",3),("max_archive_mib",251),
                          ("max_uncompressed_mib",701),("max_worker_count",True),
                          ("max_worker_count",0),("max_archive_mib",-1)):
            c=descriptor();c[key]=value
            with self.subTest(key=key,value=value):
                state=mod.PassiveNativeRelease()
                self.assertEqual(state.inspect(
                    c,actual_soabi=mod.SOABI,trusted_digest="a"*64)["state"],"DENIED")

    def test_unsigned_self_assertions_and_unknown_keys_are_rejected(self):
        c=descriptor()
        c["licenses_cleared"]=True
        self.assertEqual(mod.PassiveNativeRelease().inspect(
            c,actual_soabi=mod.SOABI,trusted_digest="a"*64)["state"],"DENIED")

    def test_rollback_never_loads_and_old_v1_v2_remain_fallback(self):
        state=mod.PassiveNativeRelease()
        state.inspect(descriptor(),actual_soabi=mod.SOABI,trusted_digest="a"*64)
        result=state.rollback()
        self.assertEqual(result["state"],"DISABLED")
        self.assertEqual(result["fallback"],"EXISTING_NATIVE_FREE_V1_V2")
        self.assertIsNone(result["candidate_sha256"])
        self.assertEqual(result["ha_installation"],"BLOCKED")

    def test_revoke_cannot_be_reenabled_in_same_session(self):
        state=mod.PassiveNativeRelease()
        state.inspect(descriptor(),actual_soabi=mod.SOABI,trusted_digest="a"*64)
        state.revoke()
        self.assertEqual(state.inspect(
            descriptor(),actual_soabi=mod.SOABI,trusted_digest="a"*64)["state"],"REVOKED")
        self.assertEqual(state.rollback()["state"],"REVOKED")
        self.assertFalse(state.diagnose()["native_activation_possible"])

    def test_incorrect_release_id_and_wheel_hash_rejected(self):
        for key,value in (("release_id","../other"),("release_id",""),
                          ("wheel_sha256","a"*63),("wheel_sha256","z"*64)):
            c=descriptor();c[key]=value
            with self.subTest(key=key):
                self.assertEqual(mod.PassiveNativeRelease().inspect(
                    c,actual_soabi=mod.SOABI,trusted_digest="a"*64)["state"],"DENIED")

if __name__=="__main__":
    unittest.main()
