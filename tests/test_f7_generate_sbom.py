"""F7 candidate SBOM coverage and security-not-asserted regression."""
from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path

p=Path(__file__).resolve().parents[1]/"scripts/f7_generate_sbom.py"
s=importlib.util.spec_from_file_location("f7_sbom",p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def fixtures():
    digest="a"*64
    paths=[
        ("rasterio.libs/libgdal-abcdefgh.so.39", "b"*64, "filename_only_not_binary_proof",
         [{"package":"gdal-libs","version":"3.13.3-r0","declared_license":"MIT"}]),
        ("rasterio/_io.cpython-314-x86_64-linux-musl.so","c"*64,
         "wheel_metadata_not_transitive_binary_license",
         [{"package":"rasterio","version":"1.5.2","declared_license":"BSD-3-Clause"}]),
        ("rasterio.libs/libunknown-abcdefgh.so.1","d"*64,"unresolved",[])
    ]
    inv={"schema":"weather_router.f7.native_candidate_inventory.v2",
         "status":"UNAPPROVED_NOT_DISTRIBUTABLE",
         "candidate":{"sha256":digest},"native_elf_count":3,
         "files":[{"path":path,"sha256":sha,"elf_magic":True,
                   "size_bytes":123, "needed":["libc.musl-x86_64.so.1"]}
                  for path,sha,_,_ in paths]}
    audit={"schema":"weather_router.f7.native_apk_license_candidates.v1",
           "status":"UNAPPROVED_NOT_DISTRIBUTABLE",
           "wheel_sha256":digest,"native_elf_count":3,
           "elf_candidates":[{"wheel_path":path,"wheel_sha256":sha,
                              "attribution_confidence":confidence,
                              "apk_source_candidates":candidates}
                             for path,sha,confidence,candidates in paths]}
    return inv,audit

class BomTests(unittest.TestCase):
    def test_three_elf_components_and_fail_closed(self):
        inv,audit=fixtures()
        bom,q=m.produce(inv,audit)
        self.assertEqual(bom["bomFormat"],"CycloneDX")
        self.assertEqual(bom["specVersion"],"1.5")
        self.assertEqual(len(bom["components"]),3)
        self.assertEqual(q["elf_expected"],3)
        self.assertEqual(q["elf_unverified_origin"],3)
        self.assertEqual(q["name_only_matches"],1)
        self.assertEqual(q["rasterio_internal_metadata_only"],1)
        self.assertEqual(len(q["unknown_components"]),1)
        self.assertFalse(q["signed_provenance"])
        self.assertFalse(q["full_safety_and_license_approval"])
        self.assertEqual(q["ha_installation"],"BLOCKED")

    def test_broken_sha_and_missing_member_rejected(self):
        inv,audit=fixtures()
        audit["wheel_sha256"]="0"*64
        with self.assertRaises(ValueError):m.produce(inv,audit)
        inv,audit=fixtures()
        audit["elf_candidates"].pop()
        with self.assertRaises(ValueError):m.produce(inv,audit)

    def test_fake_confidence_and_mismatched_elf_hash_rejected(self):
        inv,audit=fixtures()
        audit["elf_candidates"][0]["attribution_confidence"]="verified_signed"
        with self.assertRaises(ValueError):m.produce(inv,audit)
        inv,audit=fixtures()
        audit["elf_candidates"][0]["wheel_sha256"]="f"*64
        with self.assertRaises(ValueError):m.produce(inv,audit)

    def test_duplicate_elf_and_omitted_elf_rejected(self):
        inv,audit=fixtures()
        inv["files"].append(dict(inv["files"][0]))
        inv["native_elf_count"]+=1
        audit["native_elf_count"]+=1
        with self.assertRaises(ValueError):m.produce(inv,audit)
        inv,audit=fixtures()
        inv["files"].pop()
        with self.assertRaises(ValueError):m.produce(inv,audit)

if __name__=="__main__":unittest.main()
