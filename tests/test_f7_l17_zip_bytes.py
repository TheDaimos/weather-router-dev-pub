"""F7-L17 real operations preserve archive bytes and fail-closed event semantics."""
import importlib.util
import hashlib
import json
import pathlib
import tempfile
import unittest
import zipfile

PATH=pathlib.Path(__file__).resolve().parents[1]/"scripts/f7_l14_zip_api_observer.py"
spec=importlib.util.spec_from_file_location("f7zip_test",PATH)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class LiveZip(unittest.TestCase):
 def test_actual_byte_flow_and_extraction(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);mod.LOG=str(p/"events.jsonl");mod.PASS="first"
   old_write=zipfile.ZipFile.writestr;old_extract=zipfile.ZipFile.extract
   mod._trace("writestr");mod._trace("extract")
   try:
    data=b"\x7fELF"+bytes(range(32))
    w=p/"test.whl"
    with zipfile.ZipFile(w,"w") as z:
     info=zipfile.ZipInfo("rasterio.libs/unit.so")
     z.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(w) as z:
     extracted=z.extract("rasterio.libs/unit.so",p/"out")
     self.assertEqual(pathlib.Path(extracted).read_bytes(),data)
    rows=[json.loads(s) for s in (p/"events.jsonl").read_text().splitlines()]
    writes=[r for r in rows if r["operation"]=="ZipFile.writestr"]
    reads=[r for r in rows if r["operation"]=="ZipFile.extract"]
    self.assertEqual((len(writes),len(reads)),(1,1))
    self.assertEqual(writes[0]["member_name"],"rasterio.libs/unit.so")
    self.assertEqual(writes[0]["supplied_sha256"],hashlib.sha256(data).hexdigest())
    self.assertEqual(writes[0]["supplied_bytes"],len(data))
    self.assertEqual(reads[0]["extracted_path"],str(extracted))
    self.assertEqual(reads[0]["extracted_sha256"],hashlib.sha256(data).hexdigest())
    self.assertEqual(reads[0]["extracted_bytes"],len(data))
    self.assertEqual({r["repair_pass"] for r in rows},{"first"})
    self.assertEqual(w.read_bytes()[:2],b"PK")
   finally:
    zipfile.ZipFile.writestr=old_write;zipfile.ZipFile.extract=old_extract
 def test_failed_extract_not_logged(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);mod.LOG=str(p/"events.jsonl");mod.PASS="second"
   old=zipfile.ZipFile.extract;mod._trace("extract")
   try:
    with zipfile.ZipFile(p/"no.whl","w") as z:
     with self.assertRaises(KeyError):z.extract("missing.so",p)
    self.assertFalse((p/"events.jsonl").exists())
   finally:zipfile.ZipFile.extract=old
if __name__=="__main__":unittest.main()
