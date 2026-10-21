"""F7 complete native-ELF report constraints and independent clearance locks."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location(
    "f7_origin_matrix",Path(__file__).resolve().parents[1]/"scripts/f7_consolidate_elf_matrix.py")
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class OriginMatrix(unittest.TestCase):
    def fixtures(self):
        sha="a"*64
        rows=[{"wheel_path":f"rasterio/lib{i}.so","wheel_sha256":f"{i+1:064x}",
               "original_installed_sha256":None,"candidates":[]} for i in range(101)]
        joined=[{"wheel_path":x["wheel_path"],"wheel_sha256":x["wheel_sha256"],
                 "status":"RASTERIO_SOURCE_WHEEL_NO_ALPINE_APK"} for x in rows]
        b={"schema":"weather_router.f7.apk_embedded_binary_comparison.v1",
           "wheel_sha256":sha,"elf_components":rows}
        c={"schema":"weather_router.f7.apk_signed_member_correlation.v1",
           "wheel_sha256":sha,"elf_components":joined}
        d={"schema":"weather_router.f7.apk_original_license_docs.v1",
           "wheel_sha256":sha,"packages":[]}
        e={"schema":"weather_router.f7.official_apk_archive_candidates.v1",
           "wheel_sha256":sha,"packages":[]}
        return b,c,d,e

    def test_complete_101_origins_never_generate_license_clearance(self):
        md=mod.render(*self.fixtures())
        self.assertEqual(len([x for x in md.splitlines() if x.startswith("| ")])-2,101)
        self.assertIn("NICHT FREIGEGEBEN",md)
        self.assertIn("HA DEV VM 109",md)
        self.assertIn("Weitergabe",md)

    def test_cross_wheel_hash_and_per_member_change_rejected(self):
        b,c,d,e=self.fixtures()
        c["wheel_sha256"]="b"*64
        with self.assertRaises(ValueError):
            mod.render(b,c,d,e)
        b,c,d,e=self.fixtures()
        c["elf_components"][4]["wheel_sha256"]="0"*64
        with self.assertRaises(ValueError):
            mod.render(b,c,d,e)

    def test_missing_and_duplicate_native_member_rejected(self):
        b,c,d,e=self.fixtures()
        c["elf_components"].pop()
        with self.assertRaises(ValueError):
            mod.render(b,c,d,e)
        b,c,d,e=self.fixtures()
        c["elf_components"][1]["wheel_path"]=c["elf_components"][0]["wheel_path"]
        with self.assertRaises(ValueError):
            mod.render(b,c,d,e)

if __name__=="__main__":
    unittest.main()
