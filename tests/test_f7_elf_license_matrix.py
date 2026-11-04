"""F7 101-row Markdown human review evidence remains UNAPPROVED."""
import importlib.util
from pathlib import Path
import sys
import unittest

root=Path(__file__).resolve().parents[1]/"scripts"
sys.path.insert(0,str(root))
import f7_elf_license_matrix as matrix
from test_f7_generate_sbom import fixtures

class MatrixTests(unittest.TestCase):
    def test_every_elf_has_a_row_and_license_status_is_unapproved(self):
        inv,audit=fixtures()
        result=matrix.matrix(inv,audit)
        self.assertEqual(sum(1 for x in result.splitlines() if x.startswith("| ") and "| OFFEN |" in x),3)
        self.assertIn("UNBEKANNT",result)
        self.assertIn("NICHT FREIGEGEBEN",result)
        self.assertIn("filename_only_not_binary_proof",result)

    def test_missing_elf_rejected(self):
        inv,audit=fixtures()
        audit["elf_candidates"].pop()
        with self.assertRaises(ValueError):matrix.matrix(inv,audit)

if __name__=="__main__":unittest.main()
