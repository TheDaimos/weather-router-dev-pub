"""Independent P6-020 core-provider utility and public-reachability audit."""
from __future__ import annotations
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"custom_components/weather_router/consumer_capability_map.json"
REVIEW=ROOT/"docs/p6_020_provider_utility.v1.json"

from wr_public_evidence_contract import load_private_evidence_index

class P6020ProviderUtility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping=json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.review=json.loads(REVIEW.read_text(encoding="utf-8"))

    def test_exact_provider_coverage(self):
        records=self.review["providers"]
        by_id={p["provider_id"]:p for p in records}
        self.assertEqual(len(records),len(by_id),"provider duplicated")
        self.assertEqual(set(by_id),set(self.mapping["providers"]))
        self.assertEqual(self.review["summary"]["core_provider_count"],len(records))
        self.assertEqual(self.review["summary"]["with_public_contract"],len(records))
        self.assertEqual(self.review["summary"]["without_public_contract"],[])
        self.assertEqual(self.review["summary"]["removal_recommended"],0)

    def test_every_provider_has_concrete_consumer_contract(self):
        public=self.mapping["public_capabilities"]
        for provider,capabilities in self.mapping["providers"].items():
            row=next(r for r in self.review["providers"] if r["provider_id"]==provider)
            self.assertEqual(row["decision"],"keep_public_contract")
            self.assertFalse(row["removal_recommended"])
            self.assertGreater(len(row["consumer_need"]),18,provider)
            self.assertGreater(len(row["public_targets"]),0,provider)
            self.assertEqual(row["core_internal_capabilities"],len(capabilities))
            pairs={(internal,public_id) for internal,targets in capabilities.items() for public_id in targets}
            actual={(r["internal_capability"],r["public_id"]) for r in row["public_routes"]}
            self.assertEqual(actual,pairs,provider)
            self.assertEqual(len(row["public_routes"]),len(pairs),provider)
            self.assertEqual(set(row["public_targets"]),{pair[1] for pair in pairs},provider)
            for target in row["public_targets"]:
                self.assertIn(target,public,provider)

    def test_physical_and_resource_semantics_match_live_contract(self):
        for row in self.review["providers"]:
            provider=row["provider_id"]
            for path in row["public_routes"]:
                cap=path["internal_capability"]
                info=self.mapping["public_capabilities"][path["public_id"]]
                self.assertEqual(path["public_family"],info.get("family"))
                self.assertEqual(path["resource_type"],
                    self.mapping["capability_resource_types"]["providers"][provider][cap])
                self.assertEqual(path["observation_kind"],
                    self.mapping["capability_observation_semantics"]["providers"][provider][cap]["observation_kind"])

    def test_all_private_evidence_references_are_indexed(self):
        evidence_index = load_private_evidence_index(ROOT)
        for record in self.review["providers"]:
            relative=record["evidence_doc"]
            self.assertTrue(relative.startswith("docs/"))
            self.assertIn(relative, evidence_index, relative)
            self.assertEqual(record["actual_consumer_usage_telemetry"],"unknown_not_claimed")
            self.assertIn("Static contract",record["limitations"])

    def test_known_aggregate_members_and_special_contracts(self):
        by_id={r["provider_id"]:r for r in self.review["providers"]}
        civil={"bbk_mowas","nina_flood","nina_katwarn","nina_biwapp"}
        for pid in civil:
            self.assertIn("civil_protection.warning.official",by_id[pid]["public_targets"])
        tsunami={"jma","noaa_tsunami","bom_tsunami"}
        for pid in tsunami:
            self.assertIn("natural_hazards.tsunami.warnings",by_id[pid]["public_targets"])
        self.assertIn("natural_hazards.flood.warning",by_id["nina_flood"]["public_targets"])
        self.assertIn("space.aurora.probability.grid",by_id["noaa_swpc"]["public_targets"])
        self.assertEqual(len(by_id["gbif_biodiversity"]["public_targets"]),88)

if __name__=="__main__":
    unittest.main()
