"""Synthetic offline tests for F7 bounded CP314 ELF section diagnostics."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from zipfile import ZipFile

spec = importlib.util.spec_from_file_location(
    "f7_raw_elf", Path(__file__).resolve().parents[1] /
    "scripts/probe_opera_raw_elf_drift.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

MODULE = "rasterio/_io.cpython-314-x86_64-linux-musl.so"
WHEEL = "rasterio-1.5.2-cp314-cp314-linux_x86_64.whl"

def synthetic_elf(note=b"A" * 16, text=b"C" * 16):
    names = b"\0.shstrtab\0.note.gnu.build-id\0.text\0"
    blob = bytearray(640)
    blob[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", blob, 18, 62)
    struct.pack_into("<Q", blob, 40, 128)
    struct.pack_into("<HHH", blob, 58, 64, 4, 1)
    # section table at 128, 4 entries of 64 bytes
    struct.pack_into("<IIQQQQIIQQ", blob, 128 + 64, 1, 3, 0, 0, 400, len(names), 0, 0, 1, 0)
    struct.pack_into("<IIQQQQIIQQ", blob, 128 + 128, 11, 7, 0, 0, 480, len(note), 0, 0, 4, 0)
    struct.pack_into("<IIQQQQIIQQ", blob, 128 + 192, 30, 1, 0, 0, 512, len(text), 0, 0, 16, 0)
    blob[400:400 + len(names)] = names
    blob[480:480 + len(note)] = note
    blob[512:512 + len(text)] = text
    return bytes(blob)

class RawElfDifferential(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "a").mkdir()
        (self.root / "b").mkdir()
        self.left = self.root / "a" / WHEEL
        self.right = self.root / "b" / WHEEL

    def tearDown(self):
        self.temp.cleanup()

    def wheels(self, before, after, *, right_name=MODULE):
        with ZipFile(self.left, "w") as z:
            z.writestr(MODULE, before)
        with ZipFile(self.right, "w") as z:
            z.writestr(right_name, after)

    def test_build_id_only_is_a_diagnostic_not_provenance(self):
        self.wheels(synthetic_elf(), synthetic_elf(note=b"B" * 16))
        report = probe.compare(self.left, self.right)
        self.assertEqual(report["extensions_count"], 1)
        self.assertEqual(report["changed_extensions"], 1)
        self.assertTrue(report["changed_sections_by_extension"][0]["gnu_build_id_note_only"])
        self.assertIn(".note.gnu.build-id",
                      report["changed_sections_by_extension"][0]["changed_sections"])
        self.assertFalse(report["root_cause_proven"])
        self.assertFalse(report["wheel_reproducibility_proven"])
        self.assertEqual(report["ha_installation"], "BLOCKED")

    def test_text_changes_are_visible_not_blame_only_build_id(self):
        self.wheels(synthetic_elf(), synthetic_elf(note=b"B" * 16, text=b"Z" * 16))
        report = probe.compare(self.left, self.right)
        value = report["changed_sections_by_extension"][0]
        self.assertFalse(value["gnu_build_id_note_only"])
        self.assertIn(".text", value["changed_sections"])
        self.assertGreater(value["different_bytes"], 16)

    def test_same_extension_not_automatic_approval(self):
        self.wheels(synthetic_elf(), synthetic_elf())
        result = probe.compare(self.left, self.right)
        self.assertEqual(result["changed_extensions"], 0)
        self.assertFalse(result["build_inputs_attested"])
        self.assertFalse(result["wheel_reproducibility_proven"])
        self.assertEqual(result["opera_activation"], "BLOCKED")

    def test_reject_malformed_and_mismatched_extension(self):
        self.wheels(synthetic_elf(), b"not ELF")
        with self.assertRaises(ValueError):
            probe.compare(self.left, self.right)
        self.wheels(synthetic_elf(), synthetic_elf(), right_name=
                    "rasterio/_xx.cpython-314-x86_64-linux-musl.so")
        with self.assertRaises(ValueError):
            probe.compare(self.left, self.right)

    def test_symlink_input_rejected(self):
        self.wheels(synthetic_elf(), synthetic_elf())
        symlink = self.root / "link"
        symlink.symlink_to(self.left)
        with self.assertRaises(ValueError):
            probe.compare(symlink, self.right)

if __name__ == "__main__":
    unittest.main()
