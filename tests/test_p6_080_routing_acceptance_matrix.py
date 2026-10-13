"""P6-080: verify final routing evidence matrix against actual shipped core graph."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/p6_080_routing_acceptance_matrix.v1.json"
MAP = ROOT / "custom_components/weather_router/consumer_capability_map.json"


class P6080AcceptanceMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = json.loads(MATRIX.read_text(encoding="utf-8"))
        cls.map = json.loads(MAP.read_text(encoding="utf-8"))

    def test_exact_eight_domains_and_core_graph_size(self):
        recorded = self.record["core"]
        actual_public = self.map["public_capabilities"]
        actual_edges = {}
        for provider, internal in self.map["providers"].items():
            for capability_id, publics in internal.items():
                for public in publics:
                    actual_edges.setdefault(public, []).append((provider, capability_id))
        self.assertEqual(set(actual_edges), set(actual_public))
        self.assertEqual(recorded["providers"], len(self.map["providers"]))
        self.assertEqual(recorded["internal"],
                         sum(len(v) for v in self.map["providers"].values()))
        self.assertEqual(recorded["edges"], sum(map(len, actual_edges.values())))
        self.assertEqual(recorded["public"], len(actual_public))
        self.assertEqual(recorded["public"], 227)
        self.assertEqual(recorded["edges"], 286)
        self.assertEqual(recorded["multi_candidate_public"],
                         sum(len(v) > 1 for v in actual_edges.values()))
        self.assertEqual(recorded["single_candidate_public"],
                         sum(len(v) == 1 for v in actual_edges.values()))
        self.assertEqual(recorded["multi_candidate_public"], 23)
        self.assertEqual(recorded["single_candidate_public"], 204)

        domains = self.record["domains"]
        self.assertEqual(len(domains), 8)
        self.assertEqual(
            {d["id"]: d["public_ids"] for d in domains},
            {domain: sum(id_.startswith(domain + ".") for id_ in actual_public)
             for domain in {id_.split(".")[0] for id_ in actual_public}},
        )
        for domain in domains:
            self.assertTrue(domain["historical_phase"])
            self.assertTrue(domain["representative_ids"])
            for public in domain["representative_ids"]:
                self.assertIn(public, actual_public)
                self.assertTrue(public.startswith(domain["id"] + "."))

    def test_real_evidence_gates_and_no_premature_overall_claim(self):
        self.assertEqual(self.record["phase_status"], "ACTIVE")
        self.assertEqual(self.record["p7_status"], "OPEN - locked until formal P6-080 DONE")
        gates = {g["id"]: g["status"] for g in self.record["open_gates"]}
        self.assertEqual(gates.get("P6-080-HA-1"), "PASS")
        self.assertEqual(gates.get("P6-080-RELEASE"), "PASS")
        self.assertEqual(gates.get("P6-080-CATALOG-VISUAL"), "OPEN")
        self.assertEqual(gates.get("P6-080-WINNER-TRACE"), "OPEN")
        self.assertEqual(gates.get("P6-080-GESAMT"), "OPEN")
        self.assertIn("0.10.147", self.record["test_evidence"]["ha_runtime_proof"])
        self.assertIn("NOT installed", self.record["test_evidence"]["ha_runtime_proof"])
        self.assertIn("remote provider", " ".join(self.record["limitations"]))
        self.assertIn("not live network", self.record["evidence_levels"]["static_catalog"])
        self.assertIn("Do not repeat", self.record["next_runtime_batch"]["already_passed"])


if __name__ == "__main__":
    unittest.main()
