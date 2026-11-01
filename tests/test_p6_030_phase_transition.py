"""P6-030 formal transition: independent, public-safe evidence gate.

This test verifies the recorded P6-030 evidence and the exact intended
status transition. It does not claim to verify a private plan edit.
"""
from __future__ import annotations
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class P6030PhaseTransitionGate(unittest.TestCase):
    def test_complete_core_evidence_for_transition(self):
        graph = json.loads((ROOT / "docs/p6_030_orphan_graph.v1.json").read_text(encoding="utf-8"))
        contract = json.loads((ROOT / "custom_components/weather_router/consumer_capability_map.json").read_text(encoding="utf-8"))
        summary = graph["summary"]
        self.assertEqual(graph["source_contract"], "custom_components/weather_router/consumer_capability_map.json")
        self.assertEqual(summary["core_providers"], len(contract["providers"]))
        self.assertEqual(summary["public_capabilities"], len(contract["public_capabilities"]))
        self.assertEqual(summary["internal_capabilities"], sum(len(v) for v in contract["providers"].values()))
        self.assertEqual(summary["routing_edges"], sum(len(ids) for caps in contract["providers"].values() for ids in caps.values()))
        for field in ("public_orphans", "unreachable_internal", "undocumented_internal_exceptions", "empty_aggregate_intents", "topicless_internal", "missing_normalized_semantics"):
            self.assertEqual(summary[field], 0, field)
        self.assertEqual(summary["public_aggregate_intents"], 3)

    def test_single_successor_and_no_skips(self):
        gate = json.loads((ROOT / "docs/p6_030_phase_gate.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(gate["schema"], "weather_router.p6_030_phase_gate.v1")
        self.assertEqual(gate["from"], {"P6-030": "ACTIVE", "P6-040": "OPEN"})
        self.assertEqual(gate["proposed_to"], {"P6-030": "DONE", "P6-040": "ACTIVE"})
        self.assertEqual(gate["later"], {"P6-050": "OPEN", "P6-060": "OPEN", "P6-070": "OPEN", "P6-080": "OPEN", "P7": "OPEN"})
        self.assertEqual(gate["private_plan_update"], "PENDING_SEPARATE_VERIFICATION")
        self.assertEqual(gate["existing_evidence_runs"], [3598, 3599, 3600])

if __name__ == "__main__":
    unittest.main()
