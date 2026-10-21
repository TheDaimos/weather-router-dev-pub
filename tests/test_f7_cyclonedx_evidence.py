"""F7 CycloneDX native evidence unit regressions (synthetic, no native IO)."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location("f7_sbom",Path(__file__).resolve().parents[1]/"scripts/f7_cyclonedx_evidence.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class EvidenceBOM(unittest.TestCase):
    def fixtures(self,n=101):
        files=[{"path":f"rasterio.libs/libexample{i}.so","sha256":f"{i+1:064x}",
                "elf_magic":True} for i in range(n)]
        a={"schema":"weather_router.f7.native_candidate_inventory.v2",
           "status":"UNAPPROVED_NOT_DISTRIBUTABLE","files":files,
           "files_count":n,"native_elf_count":n,"candidate":{"sha256":"f"*64}}
        b={"schema":"weather_router.f7.native_apk_license_candidates.v1",
           "status":"UNAPPROVED_NOT_DISTRIBUTABLE","native_elf_count":n,
           "wheel_sha256":"f"*64,
           "elf_candidates":[{"wheel_path":x["path"],"wheel_sha256":x["sha256"],
                              "attribution_confidence":"unresolved",
                              "apk_source_candidates":[]} for x in files]}
        return a,b
    def test_realistic_101_evidence_rows_without_false_licensing(self):
        a,b=self.fixtures()
        output=mod.build(a,b)
        self.assertEqual(len(output["components"]),101)
        self.assertEqual(output["specVersion"],"1.5")
        self.assertEqual(output["components"][0]["properties"][0]["value"],"unresolved")
        self.assertIn({"name":"weather_router:approval","value":"BLOCKED"},output["metadata"]["properties"])
    def test_unknowns_are_not_guessed(self):
        a,b=self.fixtures(1)
        self.assertNotIn("licenses",mod.build(a,b)["components"][0])
    def test_tampered_hash_and_counts_rejected(self):
        a,b=self.fixtures(1)
        b["elf_candidates"][0]["wheel_sha256"]="0"*64
        with self.assertRaises(ValueError):mod.build(a,b)
        a,b=self.fixtures(1)
        a["native_elf_count"]=100
        with self.assertRaises(ValueError):mod.build(a,b)
    def test_missing_native_from_inventory_rejected(self):
        a,b=self.fixtures(1)
        a["files"][0]["elf_magic"]=False
        with self.assertRaises(ValueError):mod.build(a,b)

if __name__=="__main__":
    unittest.main()
