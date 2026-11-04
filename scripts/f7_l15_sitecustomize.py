"""CI-only auditwheel instrumentation initializer: separate real module namespaces."""
import importlib.util
from pathlib import Path
for name, path in (
    ("f7_copy_observer", "/wr/scripts/f7_auditwheel_python_trace.py"),
    ("f7_zip_observer", "/wr/scripts/f7_l14_zip_api_observer.py"),
):
    spec=importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None: raise RuntimeError("missing F7 observer "+name)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
