"""F7-L08 regression: real patchelf trace is read-only and never an approval."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"scripts/f7_verify_patchelf_trace.py"
spec=importlib.util.spec_from_file_location("f7_trace_verify",SCRIPT)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class TestTrace(unittest.TestCase):
    def test_observed_event_stays_unapproved(self):
        with tempfile.TemporaryDirectory() as p:
            source=Path(p)/"trace.jsonl"
            source.write_text(json.dumps({
                "schema":"weather_router.f7.actual_patchelf_command.v1",
                "argv":["patchelf","--set-rpath","$ORIGIN","/tmp/foo.so"],
                "target":"/tmp/foo.so","sha256_before":"a"*64,"sha256_after":"b"*64,
                "exit_code":0})+"\n")
            result=module.inspect(source)
            self.assertEqual(result["observed_commands"],1)
            self.assertEqual(result["records"][0]["sequence"],1)
            self.assertEqual(result["distribution"],"BLOCKED")
            self.assertFalse(result["all_101_elf_transformations_proven"])
            self.assertFalse(result["python_copy_and_rename_trace_complete"])

    def test_nonzero_return_cannot_pass(self):
        with tempfile.TemporaryDirectory() as p:
            source=Path(p)/"trace.jsonl"
            source.write_text(json.dumps({
                "schema":"weather_router.f7.actual_patchelf_command.v1",
                "argv":["patchelf","--set-soname","foo","/tmp/bar.so"],
                "sha256_before":None,"sha256_after":None,"exit_code":1})+"\n")
            with self.assertRaisesRegex(ValueError,"patchelf_failed"):
                module.inspect(source)

    def test_wrong_hash_rejected(self):
        with tempfile.TemporaryDirectory() as p:
            source=Path(p)/"trace.jsonl"
            source.write_text(json.dumps({
                "schema":"weather_router.f7.actual_patchelf_command.v1",
                "argv":["patchelf","--set-soname","foo","/tmp/bar.so"],
                "sha256_before":"bogus","sha256_after":None,"exit_code":0})+"\n")
            with self.assertRaisesRegex(ValueError,"invalid_digest"):
                module.inspect(source)

if __name__=="__main__":
    unittest.main()
