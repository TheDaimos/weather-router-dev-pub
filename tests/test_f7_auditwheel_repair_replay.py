"""F7-L04 provenance replay anti-forgery checks."""
import importlib.util
import pathlib
import tempfile
import unittest
import zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("f7_repair",ROOT/"scripts/f7_auditwheel_repair_replay.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
class TestRepairReplay(unittest.TestCase):
    def wheel(self,p,elems):
        with zipfile.ZipFile(p,"w") as z:
            for name,data in elems.items():z.writestr(name,data)
        return p
    def test_rejects_missing_native_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d)
            raw=self.wheel(d/"raw.whl",{"rasterio/_x.so":b"\x7fELFsample"})
            a=self.wheel(d/"first.whl",{"rasterio/_x.so":b"\x7fELFsample"})
            b=self.wheel(d/"second.whl",{"rasterio/_x.so":b"\x7fELFsample"})
            with self.assertRaisesRegex(ValueError,"unexpected_native_inventory"):
                m.report(raw,a,b,"6.8.2","patchelf")
    def test_rejects_same_output_path(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d)
            raw=self.wheel(d/"raw.whl",{"rasterio/_x.so":b"\x7fELFsample"})
            target=self.wheel(d/"out.whl",{"rasterio/_x.so":b"\x7fELFsample"})
            with self.assertRaisesRegex(ValueError,"separate outputs"):
                m.report(raw,target,target,"6.8.2","patchelf")
    def test_rejects_duplicate_member(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d)
            raw=d/"raw.whl"
            with zipfile.ZipFile(raw,"w") as z:
                z.writestr("rasterio/_x.so",b"\x7fELFsample")
                z.writestr("rasterio/_x.so",b"\x7fELFsample")
            a=self.wheel(d/"first.whl",{"rasterio/_x.so":b"\x7fELFsample"})
            b=self.wheel(d/"second.whl",{"rasterio/_x.so":b"\x7fELFsample"})
            with self.assertRaisesRegex(ValueError,"duplicate_members"):
                m.report(raw,a,b,"6.8.2","patchelf")
if __name__=="__main__":unittest.main()
