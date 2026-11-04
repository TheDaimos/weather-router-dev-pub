"""V2 registry diagnostics remain bounded and reveal no private provider data."""
from __future__ import annotations
import ast
from pathlib import Path
import unittest

FILE = Path(__file__).resolve().parents[1] / "custom_components/weather_router/consumer_raster_mosaic_api.py"
SOURCE = FILE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
FUNC = next(x for x in TREE.body if isinstance(x, ast.FunctionDef)
            and x.name == "_catalog_failure_code")
NS = {}
exec(compile(ast.fix_missing_locations(ast.Module(body=[FUNC], type_ignores=[])),
             str(FILE), "exec"), NS)
class RegistryDiagnosticsTests(unittest.TestCase):
    def test_missing_registry_file_has_specific_safe_reason(self):
        err = FileNotFoundError(2, "missing", "/config/custom_components/weather_router/provider_time_contracts.v1.json")
        self.assertEqual(NS["_catalog_failure_code"](err), "consumer_time_registry_missing")

    def test_catalog_drift_has_safe_reason_without_provider_names(self):
        self.assertEqual(NS["_catalog_failure_code"](
            ValueError("provider_time_contract_provider_inventory_drift")),
            "consumer_time_registry_invalid")

    def test_unknown_errors_do_not_leak_sensitive_details(self):
        err = ValueError("provider/private: token=SECRET")
        self.assertEqual(NS["_catalog_failure_code"](err), "consumer_contract_invalid")
        self.assertEqual(NS["_catalog_failure_code"](RuntimeError("SECRET")),
                         "consumer_contract_invalid")

if __name__ == "__main__":
    unittest.main()
