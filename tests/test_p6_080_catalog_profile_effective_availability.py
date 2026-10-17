"""P6-080: catalog must show exactly the candidates that survive profile class policy.

Execute the actual Consumer catalog function and profile policy without Home Assistant.
No network calls, user locations or credentials are required.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
import unittest

CORE = Path(__file__).resolve().parents[1] / "custom_components/weather_router"


def load_defs(file, names, namespace):
    tree = ast.parse((CORE / file).read_text(encoding="utf-8"))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in nodes} == set(names)
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    body = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
    exec(compile(body, str(CORE / file), "exec"), namespace)


PKG = "wr_p6080_catalog_isolated"
if PKG not in sys.modules:
    package = types.ModuleType(PKG)
    package.__path__ = [str(CORE)]
    sys.modules[PKG] = package
NS = {"__name__": PKG + ".consumer_api", "__package__": PKG}
load_defs("consumer_profiles.py", ("profile_allows_provider", "profile_allows_candidate"), NS)
load_defs("consumer_api.py", ("_candidate_enabled", "_capability_catalog_row"), NS)
NS.update({
    "_spatial_contexts": lambda _kind: ["global"],
    "_resource_implemented": lambda _candidate: True,
    "_public_family": lambda mapping, public_id: mapping["public_capabilities"][public_id].get("family"),
    "_public_phenomena": lambda mapping, public_id: mapping["public_capabilities"][public_id].get("phenomena", []),
    "_public_name": lambda mapping, public_id, candidates: public_id,
    "_public_metadata": lambda mapping, public_id: mapping["public_capabilities"][public_id],
    "_resolution_strategy": lambda mapping, public_id: mapping["public_capabilities"][public_id].get("strategy", "single"),
    "_public_time_semantics": lambda mapping, candidates: None,
    "_public_coverage_semantics": lambda mapping, candidates: None,
    "_public_intent_contract": lambda mapping, public_id: None,
    "_hazard_filter_options": lambda mapping, catalog, public_id: None,
})

spec = importlib.util.spec_from_file_location("p6080_routing", CORE / "consumer_routing_policy.py")
routing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routing)


class P6080CatalogDenyOnlyCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping = json.loads((CORE / "consumer_capability_map.json").read_text(encoding="utf-8"))
        cls.paths = {}
        for provider, caps in cls.mapping["providers"].items():
            for internal_id, ids in caps.items():
                for public_id in ids:
                    cls.paths.setdefault(public_id, []).append((provider, internal_id))

    def build(self, public_id, paths=None):
        paths = paths if paths is not None else self.paths[public_id]
        domain = public_id.split(".", 1)[0]
        candidates = []
        for provider, internal in paths:
            semantics = routing.normalized_candidate_semantics(
                self.mapping, public_id, provider, internal, source_class=None, unit=None
            )
            obj = SimpleNamespace(
                provider=SimpleNamespace(id=provider, router_domains=(domain,)),
                capability=SimpleNamespace(id=internal, render_mode="value", source_class="observation"),
                semantics=semantics,
            )
            candidates.append(obj)
        state = {
            "router_enabled": True,
            "enabled_domains": {domain},
            "enabled_providers": {p for p, _ in paths},
        }
        return state, candidates

    def row(self, public_id, profile=None, *, paths=None, state=None):
        default_state, candidates = self.build(public_id, paths=paths)
        return NS["_capability_catalog_row"](
            state or default_state, self.mapping, {}, candidates, public_id, profile
        )

    def test_unfiltered_catalog_has_all_227_source_paths(self):
        self.assertEqual(len(self.paths), 227)
        for public_id, source_paths in self.paths.items():
            with self.subTest(public_id=public_id):
                self.assertGreater(len(source_paths), 0)
                self.assertTrue(self.row(public_id)["available"])
                self.assertTrue(self.row(public_id)["enabled"])

    def test_all_286_edges_denied_for_each_candidate_class(self):
        inspected = 0
        for public_id, source_paths in self.paths.items():
            candidates = self.build(public_id)[1]
            for key, semantic_key in (
                ("excluded_data_origins", "data_origin"),
                ("excluded_measurement_methods", "measurement_method"),
                ("excluded_observation_kinds", "observation_kind"),
            ):
                banned_values = sorted({c.semantics[semantic_key] for c in candidates})
                with self.subTest(public_id=public_id, excluded=key):
                    row = self.row(public_id, {key: banned_values})
                    self.assertFalse(row["enabled"])
                    self.assertFalse(row["available"])
                    self.assertEqual(row["availability_basis"], "disabled")
            inspected += len(source_paths)
        self.assertEqual(inspected, 286)

    def test_partial_class_restriction_preserves_alternative(self):
        public_id = "weather.precipitation.layer"
        candidates = self.build(public_id)[1]
        groups = {}
        for c in candidates:
            groups.setdefault(c.semantics["data_origin"], []).append(c)
        self.assertGreater(len(groups), 1)
        one_origin = next(iter(groups))
        self.assertTrue(self.row(public_id, {"excluded_data_origins": [one_origin]})["available"])

    def test_provider_exclusion_and_hard_router_gates(self):
        public_id = "weather.point.temperature"
        all_providers = [provider for provider, _ in self.paths[public_id]]
        self.assertFalse(self.row(public_id, {"excluded_providers": all_providers})["available"])
        state, _ = self.build(public_id)
        for change in (
            {"router_enabled": False},
            {"enabled_domains": set()},
            {"enabled_providers": set()},
        ):
            with self.subTest(change=change):
                altered = dict(state, **change)
                row = self.row(public_id, state=altered)
                self.assertFalse(row["available"])

    def test_denial_does_not_rename_capabilities_or_claim_live_data(self):
        public_id = "weather.point.temperature"
        row = self.row(public_id, {"excluded_observation_kinds": ["forecast"]})
        self.assertEqual(row["id"], public_id)
        self.assertEqual(row["availability_basis"], "disabled")
        self.assertNotIn("provider_response", row)
        self.assertNotIn("network_response", row)


if __name__ == "__main__":
    unittest.main()
