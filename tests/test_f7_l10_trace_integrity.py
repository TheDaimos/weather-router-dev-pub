"""F7-L10 regression: preserve blocked native release and precise HTTP errors."""
import ast
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class TestL10Safety(unittest.TestCase):
 def test_http_failure_reason_retained_without_approval(self):
  s=(ROOT/"scripts/f7_probe_official_edge_openssl.py").read_text()
  self.assertIn("except urllib.error.HTTPError as exc:",s)
  self.assertIn('item["http_status_code"]=exc.code',s)
  self.assertIn('"v3_24_original_proven":False',s)
  self.assertIn('"distribution":"BLOCKED"',s)
 def test_shutil_nested_copy_does_not_duplicate_operations(self):
  s=(ROOT/"scripts/f7_auditwheel_python_trace.py").read_text()
  tree=ast.parse(s)
  wrap=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=="_wrap")
  inner=next(x for x in wrap.body if isinstance(x,ast.FunctionDef) and x.name=="traced")
  call_line=max(n.lineno for n in ast.walk(inner) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="old")
  active_before=[n for n in ast.walk(inner) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="_active" for t in n.targets) and n.lineno<call_line and isinstance(n.value,ast.Constant) and n.value.value is True]
  self.assertTrue(active_before)
if __name__=="__main__":unittest.main()
