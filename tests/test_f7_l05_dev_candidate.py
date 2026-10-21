"""F7-L05: installation candidate boundaries, read-only static regressions.

This test operates on repository files only; it neither imports optional native
modules nor touches Home Assistant. It deliberately fails closed.
"""
from __future__ import annotations
import ast
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/"custom_components/weather_router"
FORBIDDEN={".whl",".so",".pyd",".dll",".dylib",".apk",".a",".o"}

class TestF7L05DevCandidate(unittest.TestCase):
    def test_no_native_binary_distribution(self):
        native=[str(p.relative_to(PACKAGE)) for p in PACKAGE.rglob("*")
                if p.is_file() and p.suffix.lower() in FORBIDDEN]
        self.assertEqual(native, [], f"Forbidden native payload: {native}")

    def test_manifest_requirements_remain_empty(self):
        manifest=json.loads((PACKAGE/"manifest.json").read_text())
        self.assertEqual(manifest.get("requirements"), [])

    def test_versions_consistent(self):
        constants=(PACKAGE/"const.py").read_text()
        lab=(PACKAGE/"frontend/weather-router-lab.js").read_text()
        loader=(PACKAGE/"frontend/weather-router-lab-dev-loader.js").read_text()
        self.assertRegex(constants,r'DEV_BUILD_VERSION: Final = "0\\.10\\.162"')
        self.assertRegex(constants,r'DEV_LOADER_REV: Final = "0\\.10-loader-165"')
        self.assertIn('WR_LAB_BUILD_VERSION = "0.10.162"',lab)
        self.assertIn('WR_LAB_BUILD_VERSION = "0.10.162"',loader)
        self.assertIn('LOADER_REV = "0.10-loader-165"',loader)

    def test_setup_never_imports_optional_native_code(self):
        setup=(PACKAGE/"__init__.py").read_text()
        tree=ast.parse(setup)
        forbidden=("rasterio","osgeo","pyproj","opera_tile_http","opera_native_channel")
        imports=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                imports.extend(a.name for a in node.names)
            if isinstance(node,ast.ImportFrom):
                imports.append(node.module or "")
        self.assertFalse([name for name in imports if any(key in name for key in forbidden)])

    def test_no_global_native_loader_paths_in_setup(self):
        setup=(PACKAGE/"__init__.py").read_text()
        self.assertNotIn('LD_LIBRARY_PATH',setup)
        self.assertNotIn('sys.path.insert(',setup)
        self.assertNotIn('pip install',setup)
        self.assertNotIn('apk add',setup)

if __name__=="__main__":
    unittest.main()
