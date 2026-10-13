"""P6-010 independent classification audit against current core routing contract."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "custom_components/weather_router/consumer_capability_map.json"
INVENTORY = ROOT / "docs/p6_010_island_inventory.v1.json"
DECISIONS = ROOT / "docs/p6_010_island_classification.v1.json"


from wr_public_evidence_contract import load_private_evidence_index

class P6010IslandClassificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
        cls.classification = json.loads(DECISIONS.read_text(encoding="utf-8"))
        cls.by_id = {e["id"]: e for e in cls.classification["entries"]}

    def test_complete_and_no_unclassified_public_route(self):
        total = len(self.contract["public_capabilities"])
        rows = self.classification["entries"]
        self.assertEqual(self.classification["schema"], "weather_router.p6_010_island_classification.v1")
        self.assertEqual(self.classification["summary"]["total_public"], total)
        self.assertEqual(len(rows), total)
        self.assertEqual(len(self.by_id), len(rows), "duplicate decision ID")
        self.assertEqual(set(self.by_id), set(self.contract["public_capabilities"]))
        self.assertEqual(self.classification["summary"]["pending"], 0)
        self.assertEqual(self.classification["summary"]["unmapped"], 0)

    def test_each_candidate_list_matches_exact_current_runtime_map(self):
        core = self.contract
        reverse = {}
        for provider, capabilities in core["providers"].items():
            for internal, targets in capabilities.items():
                for target in targets:
                    reverse.setdefault(target, set()).add((provider, internal))
        for public_id, row in self.by_id.items():
            selected = {(x["provider"], x["capability"]) for x in row["candidates"]}
            self.assertEqual(selected, reverse.get(public_id, set()), public_id)
            self.assertEqual(row["candidate_count"], len(selected), public_id)
            self.assertGreater(len(selected), 0, public_id)
            for cand in row["candidates"]:
                provider, internal = cand["provider"], cand["capability"]
                resource = core["capability_resource_types"]["providers"][provider][internal]
                self.assertEqual(cand["resource_type"], resource, public_id)
                physical = core["capability_physical_semantics"]["providers"][provider][internal]
                self.assertEqual(cand["quantity"], physical.get("quantity"), public_id)
                observation = core["capability_observation_semantics"]["providers"][provider][internal]
                self.assertEqual(cand["observation_kind"], observation.get("observation_kind"), public_id)

    def test_decision_class_and_preserved_specialized_islands(self):
        counts = {}
        for public_id, row in self.by_id.items():
            category = row["classification"]
            counts[category] = counts.get(category, 0) + 1
            self.assertIn(category, self.classification["allowed_outcomes"], public_id)
            if row["candidate_count"] == 1:
                self.assertEqual(category, "specialized_only", public_id)
            else:
                self.assertEqual(category, "routable_multi_candidate", public_id)
            self.assertGreater(len(row["rationale"]), 110, public_id)
            self.assertIn(public_id, row["rationale"], public_id) if category == "specialized_only" else None
        self.assertEqual(counts.get("specialized_only"), self.classification["summary"]["specialized_single_candidate"])
        self.assertEqual(counts.get("routable_multi_candidate"), self.classification["summary"]["already_routable_multi_candidate"])
        self.assertEqual(sum(counts.values()), len(self.by_id))

    def test_private_evidence_references_are_covered(self):
        evidence_index = load_private_evidence_index(ROOT)
        for public_id, row in self.by_id.items():
            self.assertTrue(row.get("evidence_files"), public_id)
            for relative_path in row["evidence_files"]:
                self.assertTrue(relative_path.startswith("docs/"), public_id)
                self.assertIn(relative_path, evidence_index, f"{public_id}: {relative_path}")
            self.assertIn(row["factual_source"], {
                "approved_P2_P5_topic_closure_and_current_runtime_contract",
                "current_runtime_mapping_and_approved_topic_closures",
            })

    def test_observation_warning_and_raster_boundaries_are_preserved(self):
        for public_id, row in self.by_id.items():
            if public_id.startswith("biological_hazards."):
                self.assertEqual(row["classification"], "specialized_only")
                self.assertEqual(row["candidates"][0]["resource_type"], "raster_tile")
            if public_id.startswith("pollen."):
                self.assertEqual(row["classification"], "specialized_only")
                self.assertEqual(row["candidates"][0]["resource_type"], "value")
            if public_id.startswith("aviation."):
                self.assertEqual(row["candidates"][0]["resource_type"], "hazard_feed")
            if public_id.startswith("space.solar.suvi."):
                self.assertEqual(row["candidates"][0]["resource_type"], "image_sequence")
            if public_id in {"weather.point.uv_index", "weather.point.uv_index_max_today",
                             "weather.point.uv_index_clear_sky_max_today"}:
                self.assertEqual(row["classification"], "specialized_only")
        self.assertEqual(self.by_id["weather.precipitation.layer"]["candidate_count"], 5)
        for id_ in ("weather.radar.reflectivity", "weather.radar.precipitation",
                    "weather.radar.precipitation.quality_checked", "weather.model.precipitation_1h.layer",
                    "weather.satellite.precipitation_rate"):
            self.assertEqual(self.by_id[id_]["classification"], "specialized_only")

    def test_legacy_vs_current_mapping_delta_is_not_hidden(self):
        self.assertEqual(self.classification["summary"]["added_since_legacy"],
                         ["space.aurora.probability.grid"])
        self.assertEqual(self.classification["summary"]["removed"], 0)
        self.assertEqual(self.classification["summary"]["diagnostics_internal_only"], 0)


if __name__ == "__main__":
    unittest.main()
