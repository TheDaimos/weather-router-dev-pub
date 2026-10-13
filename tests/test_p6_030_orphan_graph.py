"""P6-030: independently enforce zero orphan paths in complete core routing graph."""
from __future__ import annotations
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"custom_components/weather_router/consumer_capability_map.json"
AUDIT=ROOT/"docs/p6_030_orphan_graph.v1.json"
METADATA=("capability_topic_assignments","capability_resource_types",
          "capability_physical_semantics","capability_source_semantics",
          "capability_observation_semantics","capability_time_semantics",
          "capability_coverage_semantics")

class P6030OrphanGraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract=json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.audit=json.loads(AUDIT.read_text(encoding="utf-8"))

    def test_exact_internal_public_and_provider_sets(self):
        contract=self.contract
        registry={f"{p}/{internal}":(p,internal,publics)
                  for p,caps in contract["providers"].items()
                  for internal,publics in caps.items()}
        internal={item["internal_ref"]:item for item in self.audit["internal_nodes"]}
        public={item["public_id"]:item for item in self.audit["public_nodes"]}
        self.assertEqual(len(internal),len(self.audit["internal_nodes"]))
        self.assertEqual(len(public),len(self.audit["public_nodes"]))
        self.assertEqual(set(internal),set(registry))
        self.assertEqual(set(public),set(contract["public_capabilities"]))
        self.assertEqual(self.audit["summary"]["core_providers"],len(contract["providers"]))
        self.assertEqual(self.audit["summary"]["routing_edges"],
                         sum(len(c[2]) for c in registry.values()))

    def test_no_orphan_internal_or_dead_public(self):
        candidates={}
        for item in self.audit["internal_nodes"]:
            key=item["internal_ref"]
            self.assertGreater(len(item["consumer_public_ids"]),0,key)
            self.assertEqual(item["classification"],"public_reachable")
            p=item["provider_id"]
            cap=item["internal_capability"]
            self.assertEqual(set(item["consumer_public_ids"]),set(self.contract["providers"][p][cap]))
            for public in item["consumer_public_ids"]:
                candidates.setdefault(public,set()).add(key)
        for item in self.audit["public_nodes"]:
            id_=item["public_id"]
            self.assertEqual(set(item["candidate_refs"]),candidates.get(id_,set()),id_)
            self.assertGreater(len(item["candidate_refs"]),0,id_)
            self.assertEqual(item["classification"],"consumer_reachable")
            self.assertEqual(item["resource_types"],
                             self.contract["public_capabilities"][id_].get("resource_types",[]))
        self.assertEqual(self.audit["summary"]["public_orphans"],0)
        self.assertEqual(self.audit["summary"]["unreachable_internal"],0)

    def test_complete_normalized_metadata_and_topic_mapping(self):
        for node in self.audit["internal_nodes"]:
            p=node["provider_id"]
            cap=node["internal_capability"]
            topic=self.contract["capability_topic_assignments"]["providers"][p][cap]
            self.assertEqual(node["topic_classification"],topic["classification"])
            self.assertEqual(node["topic_ids"],topic["topics"])
            self.assertGreater(len(topic["topics"]),0,node["internal_ref"])
            for field in METADATA:
                self.assertIn(cap,self.contract[field]["providers"][p])
                self.assertTrue(node["metadata_fields_present"][field],node["internal_ref"])
        self.assertEqual(self.audit["summary"]["topicless_internal"],0)
        self.assertEqual(self.audit["summary"]["missing_normalized_semantics"],0)

    def test_every_aggregate_has_true_source(self):
        aggregate_expected={id_:len(node["candidate_refs"])
                            for id_,node in ((x["public_id"],x) for x in self.audit["public_nodes"])
                            if self.contract["public_capabilities"][id_].get("strategy")=="aggregate"}
        aggregate_actual={x["public_id"]:x["candidate_count"]
                          for x in self.audit["aggregate_contracts"]}
        self.assertEqual(aggregate_actual,aggregate_expected)
        self.assertTrue(all(v>0 for v in aggregate_actual.values()))
        self.assertEqual(self.audit["summary"]["empty_aggregate_intents"],0)
        self.assertEqual(aggregate_actual,{
            "weather.warning.official":2,
            "natural_hazards.tsunami.warnings":3,
            "civil_protection.warning.official":4,
        })

    def test_no_hidden_exception_or_forced_runtime_claim(self):
        self.assertEqual(self.audit["summary"]["undocumented_internal_exceptions"],0)
        self.assertIn("Static graph coherence", " ".join(self.audit["rules"]))
        self.assertEqual(self.audit["status"],"GRAPH_INTEGRITY_COMPLETE_PENDING_CI")

if __name__=="__main__":
    unittest.main()
