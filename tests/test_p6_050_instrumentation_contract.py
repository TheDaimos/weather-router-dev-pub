"""P6-050: static guard for required diagnostics across the shared resolver paths."""
from __future__ import annotations
import ast
from pathlib import Path
import unittest

CORE = Path(__file__).resolve().parents[1] / "custom_components/weather_router"


def source_tree(name):
    return ast.parse((CORE / name).read_text(encoding="utf-8"))


def function_calls(tree, function):
    node = next(
        item for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == function
    )
    return {
        call.func.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "trace"
    }


class P6050InstrumentationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = source_tree("consumer_api.py")
        cls.admin = source_tree("routing_diagnostics.py")

    def test_main_resolver_instruments_all_decision_stages(self):
        observed = function_calls(self.api, "websocket_consumer_resolve")
        required = {
            "add_candidate", "candidate_check", "candidate_result",
            "candidate_attempt", "set_decision", "finish",
            "recorded_fallback_count", "winner_reason",
        }
        self.assertTrue(required.issubset(observed), sorted(required - observed))

    def test_aggregate_resolver_records_actual_results(self):
        observed = function_calls(self.api, "_resolve_aggregate_hazard")
        self.assertTrue({"candidate_result", "candidate_attempt"}.issubset(observed))

    def test_provider_call_trace_separate_from_intent_choice(self):
        actual = set()
        for name in ("_resolve_candidate", "_raster_machine_coverage"):
            actual |= function_calls(self.api, name)
        self.assertIn("candidate_provider_contact", actual)

    def test_admin_trace_endpoints_restricted(self):
        for name in (
            "websocket_routing_diagnostics",
            "websocket_routing_diagnostics_clear",
            "websocket_routing_diagnostics_subscribe",
        ):
            function = next(
                item for item in self.admin.body
                if isinstance(item, ast.AsyncFunctionDef) and item.name == name
            )
            decorators = [ast.unparse(item) for item in function.decorator_list]
            self.assertTrue(
                any("require_admin" in value for value in decorators),
                f"{name}: missing require_admin",
            )

if __name__ == "__main__":
    unittest.main()
