"""P6-060: assert bounded diagnostic memory and non-blocking consumer patterns."""
from __future__ import annotations
import ast
from collections import deque
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

CORE = Path(__file__).resolve().parents[1] / "custom_components/weather_router"
api_tree = ast.parse((CORE / "consumer_api.py").read_text(encoding="utf-8"))
diagnostics_tree = ast.parse((CORE / "routing_diagnostics.py").read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("p6060_diag_core", CORE / "routing_diagnostic_core.py")
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


def function(tree, name):
    return next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def calls(node):
    return {ast.unparse(call.func) for call in ast.walk(node) if isinstance(call, ast.Call)}


class P6060Resources(unittest.TestCase):
    def test_catalog_and_discovery_do_not_fetch_provider_resources(self):
        for name in ("websocket_consumer_discovery", "websocket_consumer_capabilities"):
            names = calls(function(api_tree, name))
            self.assertFalse(any("_resolve_candidate" in item for item in names))
            self.assertFalse(any("_raster_machine_coverage" in item for item in names))

    def test_mapping_and_provider_construction_off_event_loop(self):
        for name in ("_async_mapping", "_async_hazard_types", "_async_providers"):
            names = calls(function(api_tree, name))
            self.assertIn("hass.async_add_executor_job", names, name)

    def test_resolvers_use_serial_await_in_candidate_loop(self):
        for name in ("websocket_consumer_resolve", "_resolve_aggregate_hazard"):
            node = function(api_tree, name)
            await_calls = [
                (item, await_node)
                for item in ast.walk(node) if isinstance(item, (ast.For, ast.AsyncFor))
                for await_node in ast.walk(item) if isinstance(await_node, ast.Await)
                if isinstance(await_node.value, ast.Call)
                and isinstance(await_node.value.func, ast.Name)
                and await_node.value.func.id == "_resolve_candidate"
            ]
            self.assertTrue(await_calls, name)
            self.assertFalse(any("asyncio.gather" in x or "create_task" in x for x in calls(node)))

    def test_trace_ring_is_bounded_without_ha(self):
        node = function(diagnostics_tree, "_store")
        program = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
        namespace = {
            "Any": object,
            "HomeAssistant": object,
            "DOMAIN": "weather_router",
            "_STORE_KEY": "_synthetic_test_store",
            "ROUTING_DIAGNOSTIC_LIMIT": diag.ROUTING_DIAGNOSTIC_LIMIT,
            "deque": deque,
            "utc_now": diag.utc_now,
        }
        exec(compile(program, "<isolated_route_store>", "exec"), namespace)
        hass = SimpleNamespace(data={})
        trace_store = namespace["_store"](hass)
        for index in range(diag.ROUTING_DIAGNOSTIC_LIMIT + 25):
            trace_store["traces"].append({"id": index})
        self.assertEqual(len(trace_store["traces"]), diag.ROUTING_DIAGNOSTIC_LIMIT)
        self.assertEqual(trace_store["traces"][0]["id"], 25)

    def test_trace_summaries_are_bounded_and_redacted(self):
        big = {
            "secret": "synthetic_value",
            "records": list(range(300)),
            "name": "x" * 6000,
        }
        safe = diag.diagnostic_value(big)
        self.assertEqual(safe["secret"], "<redacted>")
        self.assertLessEqual(len(safe["name"]), 4000)
        self.assertEqual(len(safe["records"]), 201)
        self.assertEqual(safe["records"][-1]["_truncated_items"], 100)

if __name__ == "__main__":
    unittest.main()
