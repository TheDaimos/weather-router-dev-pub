"""F7 group-size audit without deletion or native import."""
import importlib.util
import unittest
from pathlib import Path

p=Path(__file__).resolve().parents[1]/"scripts/f7_native_size_scope.py"
s=importlib.util.spec_from_file_location("f7_size",p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class NativeSizeTests(unittest.TestCase):
    def test_hotspots_measured_but_never_pruned(self):
        rows=[("rasterio.libs/libSFCGAL-abcd1234.so", 40),
              ("rasterio.libs/libopenblas-abcd1234.so",35),
              ("rasterio.libs/liblapack-abcd1234.so",8),
              ("rasterio.libs/libgdal-abcd1234.so",27)]
        inv={"schema":"weather_router.f7.native_candidate_inventory.v2",
             "status":"UNAPPROVED_NOT_DISTRIBUTABLE",
             "native_elf_count":len(rows),
             "files":[{"path":a,"size_bytes":b,"elf_magic":True} for a,b in rows]}
        res=m.scope(inv)
        self.assertEqual(res["native_elf_count"],4)
        self.assertEqual(res["native_elf_uncompressed_bytes"],110)
        self.assertEqual(res["size_groups"]["SFCGAL"]["bytes"],40)
        self.assertEqual(res["size_groups"]["OpenBLAS"]["bytes"],35)
        self.assertFalse(res["safe_to_remove_transitive_dependencies"])
        self.assertEqual(res["opera_activation"],"BLOCKED")

    def test_missing_elf_records_fail_closed(self):
        inv={"schema":"weather_router.f7.native_candidate_inventory.v2",
             "status":"UNAPPROVED_NOT_DISTRIBUTABLE","native_elf_count":2,"files":[]}
        with self.assertRaises(ValueError):m.scope(inv)
if __name__=="__main__":unittest.main()
