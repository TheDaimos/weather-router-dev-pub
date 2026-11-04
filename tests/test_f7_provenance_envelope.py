"""F7 evidence binding tests: all evidence is explicitly UNSIGNED and blocked."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location("f7_provenance",Path(__file__).resolve().parents[1]/"scripts/f7_provenance_envelope.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class ProvenanceEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        files=[{"path":f"rasterio.libs/module-{i}.so","sha256":f"{i+1:064x}",
                "elf_magic":True} for i in range(101)]
        self.docs={
            mod.FILES[0]:{"schema":"weather_router.f7.native_candidate_inventory.v2",
                          "status":"UNAPPROVED_NOT_DISTRIBUTABLE",
                          "candidate":{"sha256":"a"*64},"files":files,
                          "files_count":101,"native_elf_count":101},
            mod.FILES[1]:{"wheel_sha256":"a"*64,"native_elf_count":101},
            mod.FILES[2]:{"wheel_sha256":"a"*64,"ha_installation":"BLOCKED",
                          "container_image_digest":"sha256:"+"b"*64},
            mod.FILES[3]:{"bomFormat":"CycloneDX","components":[
                {"name":x["path"],"hashes":[{"alg":"SHA-256","content":x["sha256"]}]} for x in files]},
            mod.FILES[4]:{"wheel_sha256":"a"*64,"elf_included":101},
            mod.FILES[5]:{"ha_installation":"BLOCKED","status":"NOT_SCANNED"},
        }
        self.write()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self):
        for name,doc in self.docs.items():
            (self.root/name).write_text(json.dumps(doc),encoding="utf-8")

    def test_full_101_file_binding_is_still_unsigned_and_blocked(self):
        record=mod.build(self.root)
        self.assertEqual(len(record["evidence_file_sha256"]),6)
        self.assertEqual(record["native_elf_count"],101)
        self.assertEqual(record["status"],"BOUND_UNAPPROVED_EVIDENCE_ONLY")
        self.assertFalse(record["signature_envelope"]["independent_signature_verified"])
        self.assertIsNone(record["signature_envelope"]["trusted_public_key_id"])
        self.assertFalse(record["license_review_complete"])
        self.assertEqual(record["ha_installation"],"BLOCKED")

    def test_cross_artifact_candidate_hash_mismatch_rejected(self):
        self.docs[mod.FILES[4]]["wheel_sha256"]="f"*64
        self.write()
        with self.assertRaises(ValueError):
            mod.build(self.root)

    def test_bom_missing_or_mutated_single_elf_rejected(self):
        self.docs[mod.FILES[3]]["components"][0]["hashes"][0]["content"]="1"*64
        self.write()
        with self.assertRaises(ValueError):
            mod.build(self.root)

    def test_symlink_and_missing_input_rejected(self):
        source=self.root/mod.FILES[5]
        source.unlink()
        source.symlink_to(self.root/mod.FILES[0])
        with self.assertRaises(ValueError):
            mod.build(self.root)

    def test_unpinned_image_and_unblocked_security_rejected(self):
        self.docs[mod.FILES[2]]["container_image_digest"]=None
        self.write()
        with self.assertRaises(ValueError):
            mod.build(self.root)
        self.docs[mod.FILES[2]]["container_image_digest"]="sha256:"+"b"*64
        self.docs[mod.FILES[5]]["ha_installation"]="APPROVED"
        self.write()
        with self.assertRaises(ValueError):
            mod.build(self.root)

if __name__=="__main__":
    unittest.main()
