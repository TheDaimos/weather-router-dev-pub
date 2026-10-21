"""Offline Alpine CVE candidate assessment, no network or apk process in tests."""
import importlib.util
import unittest
from pathlib import Path

p=Path(__file__).resolve().parents[1]/"scripts/f7_alpine_secdb_candidates.py"
s=importlib.util.spec_from_file_location("f7_apk_secdb",p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def fixture():
    snap={"schema":"weather_router.f7.build_input_snapshot.v1",
          "status":"EVIDENCE_ONLY_NOT_REPRODUCIBLE",
          "apk_packages":[{"name":"gdal-libs","origin":"gdal","version":"3.13.3-r0"},
                          {"name":"proj","origin":"proj","version":"9.8.1-r0"}]}
    feeds=[{"distroversion":"v3.24","reponame":"main",
            "packages":[{"pkg":{"name":"gdal","secfixes":{
                "3.13.4-r0":["CVE-2099-0001"]}}}]},
           {"distroversion":"v3.24","reponame":"community","packages":[]}]
    return snap,feeds

class SecdbCandidateTests(unittest.TestCase):
    def test_version_comparison_is_a_warning_not_security_clearance(self):
        snapshot,feeds=fixture()
        def fake_compare(a,b):
            self.assertEqual((a,b),("3.13.3-r0","3.13.4-r0"))
            return "<"
        result=m.assess(snapshot,feeds,compare=fake_compare)
        self.assertEqual(result["packages_with_possible_findings"],1)
        self.assertEqual(result["packages_without_feed_match"],1)
        self.assertEqual(result["packages"][0]["potential_advisory_candidates"][0]["advisory"],"CVE-2099-0001")
        self.assertEqual(result["packages"][0]["assessment"],"POSSIBLE_UNFIXED_ADVISORIES")
        self.assertEqual(result["packages"][1]["assessment"],"UNKNOWN_NOT_IN_FEED")
        self.assertEqual(result["status"],"DIAGNOSTIC_ONLY_NOT_SECURITY_CLEARED")
        self.assertFalse(result["scan_claims_all_vulnerabilities"])
        self.assertEqual(result["ha_installation"],"BLOCKED")

    def test_fixed_version_does_not_prove_no_cve(self):
        snap,feeds=fixture()
        result=m.assess(snap,feeds,compare=lambda a,b:">")
        self.assertEqual(result["packages"][0]["assessment"],
                         "NO_LISTED_UNFIXED_FIXES_NOT_A_CLEARANCE")

    def test_wrong_distro_and_broken_versions_rejected(self):
        snap,feeds=fixture()
        feeds[0]["distroversion"]="v3.23"
        with self.assertRaises(ValueError):m.assess(snap,feeds,compare=lambda a,b:"<")
        snap,feeds=fixture()
        snap["apk_packages"][0]["version"]="$(cmd)"
        with self.assertRaises(ValueError):m.assess(snap,feeds,compare=lambda a,b:"<")

if __name__=="__main__":unittest.main()
