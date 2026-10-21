"""Synthetic F7 original provenance release-gate negative regressions."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location("f7_release_gate",Path(__file__).resolve().parents[1]/"scripts/f7_original_binary_release_gate.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
SHA="a"*64
def fixture():
    left={"schema":"weather_router.f7.apk_embedded_binary_comparison.v1",
          "wheel_sha256":SHA,"native_elf_count":101,"ha_installation":"BLOCKED",
          "elf_components":[{"wheel_path":f"lib{i}.so","wheel_sha256":f"{i+1:064x}",
                              "original_installed_sha256":f"{i+1:064x}"} for i in range(101)]}
    right={"schema":"weather_router.f7.apk_signed_member_correlation.v1",
           "wheel_sha256":SHA,"native_elf_count":101,"ha_installation":"BLOCKED",
           "archive_elf_matches_installed_count":1,
           "elf_components":[{"wheel_path":f"lib{i}.so","wheel_sha256":f"{i+1:064x}",
             "status":"SIGNED_APK_MEMBER_EQUALS_INSTALLED_NOT_REPAIRED_ELF" if i==0 else "APK_BINARY_OR_SIGNATURE_NOT_VERIFIED",
             "signed_archive_matches":[{"apk_elf_sha256":f"{i+1:064x}","apk_sha256":"f"*64,
                                        "external_key_attestation":False}] if i==0 else [],
             "auditwheel_transformation_reproduced_from_apk":False,
             "independent_key_trust":False} for i in range(101)]}
    license={"schema":"weather_router.f7.apk_original_license_docs.v1","wheel_sha256":SHA,
             "ha_installation":"BLOCKED",
             "original_copyright_and_distribution_obligations_reviewed":False}
    return left,right,license
class SourceChain(unittest.TestCase):
    def test_partial_original_match_is_explicitly_not_license_or_release(self):
        output=m.assess(*fixture())
        self.assertEqual(output["apk_member_matches_to_installed"],1)
        self.assertEqual(output["native_elf_count"],101)
        self.assertEqual(output["ha_installation"],"BLOCKED")
        self.assertFalse(output["auditwheel_transform_verified"])
    def test_digest_mutation_rejected(self):
        a,b,c=fixture()
        b["elf_components"][13]["wheel_sha256"]="0"*64
        with self.assertRaises(ValueError):m.assess(a,b,c)
    def test_unverified_source_must_not_pretend_sourced(self):
        a,b,c=fixture()
        b["elf_components"][2]["status"]="SIGNED_APK_MEMBER_EQUALS_INSTALLED_NOT_REPAIRED_ELF"
        with self.assertRaises(ValueError):m.assess(a,b,c)
    def test_unverified_signature_and_license_cannot_promote(self):
        a,b,c=fixture()
        b["elf_components"][0]["signed_archive_matches"][0]["external_key_attestation"]=True
        with self.assertRaises(ValueError):m.assess(a,b,c)
        a,b,c=fixture()
        c["original_copyright_and_distribution_obligations_reviewed"]=True
        with self.assertRaises(ValueError):m.assess(a,b,c)
    def test_missing_elf_and_fake_release_rejected(self):
        a,b,c=fixture();b["elf_components"].pop()
        with self.assertRaises(ValueError):m.assess(a,b,c)
        a,b,c=fixture();a["ha_installation"]="APPROVED"
        with self.assertRaises(ValueError):m.assess(a,b,c)
if __name__=="__main__":unittest.main()
