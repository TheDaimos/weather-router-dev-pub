"""P6-010 inventory consistency: live public routing paths, no invented island acceptance."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components/weather_router/consumer_capability_map.json"
INVENTORY = ROOT / "docs/p6_010_island_inventory.v1.json"


class P6010IslandInventoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads(SOURCE.read_text(encoding="utf-8"))
        cls.inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))

    def test_schema_and_current_scope(self):
        report = self.inventory
        self.assertEqual(report["schema"], "weather_router.p6_010_island_inventory.v1")
        self.assertEqual(report["status"], "PARTIAL_CLASSIFICATION_P6_010_ACTIVE")
        self.assertEqual(report["summary"]["core_providers"], len(self.source["providers"]))
        self.assertEqual(report["summary"]["current_public_capabilities"], len(self.source["public_capabilities"]))
        self.assertEqual(len(report["entries"]), len(self.source["public_capabilities"]))

    def test_each_public_route_has_actual_candidate(self):
        contract = self.source
        reverse = {}
        for provider, mapping in contract["providers"].items():
            for internal, publics in mapping.items():
                for public_id in publics:
                    reverse.setdefault(public_id, set()).add((provider, internal))
        recorded = {entry["id"]: entry for entry in self.inventory["entries"]}
        self.assertEqual(set(recorded), set(contract["public_capabilities"]))
        self.assertEqual(set(reverse), set(recorded))
        for public_id, item in recorded.items():
            expected = reverse[public_id]
            actual = {(candidate["provider"], candidate["capability"]) for candidate in item["candidates"]}
            self.assertEqual(actual, expected, public_id)
            self.assertEqual(item["candidate_count"], len(expected), public_id)
            self.assertGreater(item["candidate_count"], 0, public_id)

    def test_classification_does_not_overclaim_unreviewed_paths(self):
        decisions = {}
        for entry in self.inventory["entries"]:
            classification = entry["classification"]
            decisions[classification] = decisions.get(classification, 0) + 1
            if entry["candidate_count"] > 1:
                self.assertEqual(classification, "routable_multi_candidate", entry["id"])
            elif entry["id"].startswith("biological_hazards.occurrence."):
                self.assertEqual(classification, "specialized_only", entry["id"])
            else:
                self.assertEqual(classification, "pending_semantic_review", entry["id"])
        summary = self.inventory["summary"]
        self.assertEqual(decisions.get("routable_multi_candidate"), summary["with_multiple_direct_candidates"])
        self.assertEqual(decisions.get("specialized_only"), summary["validated_specialized_bio"])
        self.assertEqual(decisions.get("pending_semantic_review"), summary["requires_semantic_review"])
        self.assertEqual(summary["unmapped_public_capabilities"], [])
        self.assertEqual(summary["with_single_direct_candidate"] + summary["with_multiple_direct_candidates"], len(self.inventory["entries"]))

    def test_legacy_delta_is_explicit_and_not_a_live_assertion(self):
        report = self.inventory
        summary = report["summary"]
        self.assertGreaterEqual(summary["current_public_capabilities"], summary["legacy_public_capabilities"])
        self.assertEqual(summary["added_since_legacy"], ["space.aurora.probability.grid"])
        self.assertFalse(summary["legacy_missing_in_current"])
        self.assertNotEqual(
            summary["historical_classification_distribution"]["single_candidate_with_phenomenon_peers"],
            summary["historical_findings_isolation_counts"]["single_candidate_with_phenomenon_peers"],
            "The historical embedded counts must remain explicitly distinguishable",
        )


if __name__ == "__main__":
    unittest.main()
