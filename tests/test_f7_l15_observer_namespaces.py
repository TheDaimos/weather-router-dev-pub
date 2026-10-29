"""F7-L15 regression for observer namespace separation and unchanged operations."""
from pathlib import Path
import ast
import unittest
ROOT=Path(__file__).resolve().parents[1]
class TestNamespace(unittest.TestCase):
    def test_separate_modules_not_concatenated(self):
        initializer=(ROOT/"scripts/f7_l15_sitecustomize.py").read_text()
        shell=(ROOT/"scripts/ci_opera_musl_wheel_prototype.sh").read_text()
        self.assertIn('spec_from_file_location(name, path)',initializer)
        self.assertIn('spec.loader.exec_module(module)',initializer)
        self.assertIn("f7_copy_observer",initializer)
        self.assertIn("f7_zip_observer",initializer)
        self.assertIn("cp scripts/f7_l15_sitecustomize.py",shell)
        self.assertNotIn("cat scripts/f7_l14_zip_api_observer.py >>",shell)
    def test_trace_targets_distinct(self):
        copy=ast.parse((ROOT/"scripts/f7_auditwheel_python_trace.py").read_text())
        zipp=ast.parse((ROOT/"scripts/f7_l14_zip_api_observer.py").read_text())
        def log_value(tree):
            node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="LOG" for t in n.targets))
            return ast.literal_eval(node.value)
        self.assertNotEqual(log_value(copy),log_value(zipp))
        self.assertIn("python-operations",log_value(copy))
        self.assertIn("zip-operations",log_value(zipp))
    def test_copy_and_zip_shims_return_original_results(self):
        copy=(ROOT/"scripts/f7_auditwheel_python_trace.py").read_text()
        zipp=(ROOT/"scripts/f7_l14_zip_api_observer.py").read_text()
        self.assertIn("result = old(*args, **kwargs)",copy)
        self.assertIn("result = original(self, *args, **kwargs)", zipp)
        self.assertIn("return result",copy)
        self.assertIn("return result",zipp)
if __name__=="__main__":unittest.main()
