"""P6-040: capability catalog must honor all candidate-class profile exclusions.

Exercises the real catalog-row and routing-policy functions in isolation, without
Home Assistant, network access, or provider requests.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
import unittest

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "custom_components/weather_router/consumer_api.py"
PROFILES = ROOT / "custom_components/weather_router/consumer_profiles.py"


def extract(path: Path, names: set[str], namespace: dict):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in functions} == names
    code = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    exec(compile(code, str(path), "exec"), namespace)


NS = {"Any": Any, "Mapping": Mapping, "Candidate": object}
extract(PROFILES, {"profile_allows_provider", "profile_allows_candidate"}, NS)
extract(API, {"_candidate_enabled", "_capability_catalog_row"}, NS)
NS.update({
    "_spatial_contexts": lambda _: ["point"],
    "_resource_implemented": lambda _: True,
    "_public_family": lambda mapping, public_id: "point",
    "_public_phenomena": lambda mapping, public_id: ["precipitation"],
    "_public_name": lambda mapping, public_id, candidates: "Synthetic",
    "_public_metadata": lambda mapping, public_id: {},
    "_resolution_strategy": lambda mapping, public_id: "single",
    "_public_time_semantics": lambda mapping, candidates: None,
    "_public_coverage_semantics": lambda mapping, candidates: None,
    "_public_intent_contract": lambda mapping, public_id: None,
    "_hazard_filter_options": lambda mapping, catalog, public_id: None,
})

catalog_row = NS["_capability_catalog_row"]


class P6040CatalogCandidateFilters(unittest.TestCase):
    def setUp(self):
        self.id = "weather.point.synthetic"
        self.state = {"router_enabled": True, "enabled_domains": {"weather"},
                      "enabled_providers": {"synthetic_provider"}}
        self.candidate = SimpleNamespace(
            provider=SimpleNamespace(id="synthetic_provider", router_domains=("weather",)),
            capability=SimpleNamespace(render_mode="value", source_class="observation"),
            semantics={"data_origin": "satellite", "measurement_method": "remote_sensing",
                       "observation_kind": "observation"},
        )

    def row(self, profile, candidates=None):
        return catalog_row(
            self.state, {}, {}, candidates if candidates is not None else [self.candidate],
            self.id, profile,
        )

    def test_unprofiled_candidate_available(self):
        row = self.row(None)
        self.assertTrue(row["enabled"])
        self.assertTrue(row["available"])

    def test_each_denied_candidate_class_marks_unavailable(self):
        policies = [
            {"excluded_data_origins": ["satellite"]},
            {"excluded_measurement_methods": ["remote_sensing"]},
            {"excluded_observation_kinds": ["observation"]},
        ]
        for policy in policies:
            with self.subTest(policy=policy):
                row = self.row(policy)
                self.assertFalse(row["enabled"])
                self.assertFalse(row["available"])
                self.assertEqual(row["availability_basis"], "disabled")

    def test_provider_deny_matches_candidate_class_deny(self):
        row = self.row({"excluded_providers": ["synthetic_provider"]})
        self.assertFalse(row["enabled"])
        self.assertFalse(row["available"])

    def test_single_eligible_candidate_preserves_availability(self):
        alternative = SimpleNamespace(
            provider=self.candidate.provider, capability=self.candidate.capability,
            semantics={"data_origin": "radar", "measurement_method": "radar",
                       "observation_kind": "observation"},
        )
        row = self.row({"excluded_data_origins": ["satellite"]},
                       [self.candidate, alternative])
        self.assertTrue(row["enabled"])
        self.assertTrue(row["available"])

    def test_global_provider_off_never_overridden(self):
        self.state["enabled_providers"] = set()
        row = self.row({})
        self.assertFalse(row["enabled"])
        self.assertFalse(row["available"])

if __name__ == "__main__":
    unittest.main()
