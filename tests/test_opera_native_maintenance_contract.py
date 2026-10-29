"""No auto-update or stale-ABI acceptance for WeatherRouter native extensions."""
import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).resolve().parents[1]/"custom_components/weather_router/opera_native_maintenance_contract.py"
s=importlib.util.spec_from_file_location("f7_maintenance",p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def release():
    return {
        "python_soabi":"cpython-314-x86_64-linux-musl",
        "wheel_sha256":"a"*64, "rasterio":"1.5.2","gdal":"3.13.3",
        "proj":"9.8.1","alpine_image_digest":"sha256:"+"b"*64,
        "apk_db_sha256":"c"*64, "license_matrix_sha256":"d"*64,
        "security_advisory_snapshot_sha256":"e"*64}

class NativeMaintenanceTests(unittest.TestCase):
    def test_identical_does_not_auto_approve(self):
        result=m.compare(release(),release())
        self.assertFalse(result["changed_fields"])
        self.assertFalse(result["approved_new_release"])
        self.assertFalse(result["safe_auto_upgrade"])
        self.assertEqual(result["ha_installation"],"BLOCKED")

    def test_python_abi_and_new_license_or_security_digest_trigger_review(self):
        for key,new in (("python_soabi","cpython-315-x86_64-linux-musl"),
                        ("gdal","3.14.0"),
                        ("license_matrix_sha256","1"*64),
                        ("security_advisory_snapshot_sha256","2"*64)):
            nxt=release();nxt[key]=new
            with self.subTest(field=key):
                result=m.compare(release(),nxt)
                self.assertIn(key,result["changed_fields"])
                self.assertTrue(result["requires_new_full_license_and_cve_review"])
                self.assertTrue(result["requires_native_abi_and_ha_compatibility_test"])
                self.assertEqual(result["opera_activation"],"BLOCKED")

    def test_incomplete_or_forged_inputs_denied(self):
        a=release();b=release();b.pop("gdal")
        with self.assertRaises(ValueError):m.compare(a,b)
        b=release();b["apk_db_sha256"]="bad"
        with self.assertRaises(ValueError):m.compare(a,b)
if __name__=="__main__":unittest.main()
