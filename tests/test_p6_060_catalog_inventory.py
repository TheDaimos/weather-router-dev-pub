"""P6-060: per-request catalog inventory avoids redundant provider inspections."""
from __future__ import annotations

import ast
from collections import namedtuple
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest

CORE = Path(__file__).resolve().parents[1] / "custom_components/weather_router"
SOURCE = (CORE / "consumer_api.py").read_text(encoding="utf-8")
Candidate = namedtuple("Candidate", "provider capability public_id semantics score")
spec = importlib.util.spec_from_file_location("p6060_routing", CORE / "consumer_routing_policy.py")
routing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routing)


class Provider:
    def __init__(self, name):
        self.id = name
        self.inspections = 0
        self._caps = [SimpleNamespace(id=f"{name}_one", source_class="observation", unit=None)]

    def capabilities(self):
        self.inspections += 1
        return list(self._caps)


def isolate_candidates():
    tree = ast.parse(SOURCE)
    definition = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "_candidates"
    )
    module = ast.fix_missing_locations(ast.Module(body=[definition], type_ignores=[]))
    namespace = {
        "Any": Any,
        "Candidate": Candidate,
        "_provider_capability_map": lambda p: {cap.id: cap for cap in p.capabilities()},
        "normalized_candidate_semantics": routing.normalized_candidate_semantics,
        "candidate_score": routing.candidate_score,
    }
    exec(compile(module, str(CORE / "consumer_api.py"), "exec"), namespace)
    return namespace["_candidates"]


class P6060CatalogInventory(unittest.TestCase):
    def test_cached_per_request_candidates_identical_to_uncached(self):
        ids = [f"weather.synthetic.cap_{i}" for i in range(12)]
        providers = {name: Provider(name) for name in ("provider_a", "provider_b")}
        mapping = {
            "providers": {
                name: {f"{name}_one": list(ids)} for name in providers
            },
            "public_capabilities": {
                public_id: {"family": "point"} for public_id in ids
            },
        }
        candidates = isolate_candidates()
        baseline = [
            [(c.provider.id, c.capability.id, c.score) for c in candidates(providers, mapping, public_id)]
            for public_id in ids
        ]
        self.assertEqual(
            sum(p.inspections for p in providers.values()),
            len(ids) * len(providers),
        )
        for p in providers.values():
            p.inspections = 0
        inventory = {
            p.id: {cap.id: cap for cap in p.capabilities()} for p in providers.values()
        }
        optimized = [
            [(c.provider.id, c.capability.id, c.score)
             for c in candidates(providers, mapping, public_id, capability_maps=inventory)]
            for public_id in ids
        ]
        self.assertEqual(baseline, optimized)
        self.assertEqual(
            sum(p.inspections for p in providers.values()),
            len(providers),
        )

    def test_no_persistent_cache_after_provider_changes(self):
        provider = Provider("provider_a")
        mapping = {
            "providers": {"provider_a": {"provider_a_one": ["weather.synthetic.cap"]}},
            "public_capabilities": {"weather.synthetic.cap": {"family": "point"}},
        }
        candidates = isolate_candidates()
        before = candidates({"provider_a": provider}, mapping, "weather.synthetic.cap")
        provider._caps = []
        after = candidates({"provider_a": provider}, mapping, "weather.synthetic.cap")
        self.assertEqual(len(before), 1)
        self.assertEqual(after, [])

if __name__ == "__main__":
    unittest.main()
